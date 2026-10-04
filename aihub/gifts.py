"""Atomic, idempotent transfer of supplemental AI points only."""
import uuid
import secrets
from decimal import Decimal
from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import transaction
from django.db.models import F, Prefetch
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from core import permissions as perms
from core.models import ChatMessage
from core.messages import requested_channel, serialize, visible_messages
from .models import PointGift, PointGiftReceipt, Allowance, PoolSettings
from .service import allowance, pool_settings, require_member, Q8

class GiftForm(forms.Form):
    request_id = forms.UUIDField()
    kind = forms.ChoiceField(choices=[('transfer','转账'),('packet','红包')])
    mode = forms.ChoiceField(choices=[('equal','均分'),('random','拼手气')])
    points = forms.DecimalField(max_digits=15, decimal_places=6, min_value=Decimal('.000001'), max_value=Decimal('1000000000'))
    count = forms.IntegerField(min_value=1, max_value=100)
    greeting = forms.CharField(required=False, max_length=80)

def writer_lock():
    # The first query is a write; API billing takes this same lock.
    PoolSettings.objects.filter(pk=1).update(enabled=F('enabled'))
    return pool_settings()

def refund_locked(gift):
    if gift.closed_at: return
    amount=gift.remaining_cny
    member=allowance(gift.sender)
    Allowance.objects.filter(pk=member.pk).update(extra_balance=F('extra_balance')+amount)
    gift.refunded_cny=amount;gift.remaining_cny=Decimal('0');gift.closed_at=timezone.now()
    gift.save(update_fields=['refunded_cny','remaining_cny','closed_at'])

def expire_gifts():
    due=PointGift.objects.filter(closed_at__isnull=True,expires_at__lte=timezone.now())
    if not due.exists(): return 0
    with transaction.atomic():
        writer_lock()
        rows=list(due.select_for_update().select_related('sender')[:500])
        for gift in rows: refund_locked(gift)
    return len(rows)

def receipt_prefetch(user):
    return Prefetch('receipts', queryset=PointGiftReceipt.objects.filter(user=user), to_attr='viewer_receipts')

def card(gift,user):
    receipt=(gift.viewer_receipts[0] if gift.viewer_receipts else None) if hasattr(gift,'viewer_receipts') else gift.receipts.filter(user=user).first()
    status='已领完' if gift.claimed_count==gift.count else '已退回' if gift.closed_at else '已过期' if gift.expires_at<=timezone.now() else '待领取'
    return {'id':str(gift.pk),'kind':gift.kind,'mode':gift.mode,'title':'积分转账' if gift.kind=='transfer' else '积分红包',
            'greeting':gift.greeting,'points':str(gift.amount_cny*100),'status':status,
            'claimed_points':str(receipt.amount_cny*100) if receipt else None,
            'claimed_count':gift.claimed_count,'count':gift.count,'mine':gift.sender_id==user.pk,
            'can_claim':not gift.closed_at and gift.expires_at>timezone.now() and not receipt and (
                gift.message.room!='private' or gift.message.recipient_id==user.pk),
            'can_refund':gift.sender_id==user.pk and gift.kind=='transfer' and not gift.closed_at,
            'expires_at':gift.expires_at.isoformat(),'refunded_points':str(gift.refunded_cny*100),
            'detail_url':'/messages/points/'+str(gift.pk)+'/',
            'claim_url':'/messages/points/'+str(gift.pk)+'/claim/'}

def permitted_gift(request,pk):
    require_member(request.user)
    gift=get_object_or_404(PointGift.objects.select_related('sender','message'),pk=pk)
    message=gift.message
    if message.room=='private' and request.user.pk not in (message.author_id,message.recipient_id):
        raise PermissionDenied('此积分消息仅双方可见。')
    if message.room not in ('private','developers','public'): raise PermissionDenied
    return gift

@login_required
@never_cache
@require_POST
def send(request):
    require_member(request.user);expire_gifts()
    peer,key,_,_=requested_channel(request)
    form=GiftForm(request.POST)
    if not form.is_valid(): return JsonResponse({'error':'请填写有效的积分、份数和祝福语。','fields':form.errors.get_json_data()},status=400)
    if request.POST.get('confirm')!='yes': return JsonResponse({'error':'请确认发送积分。'},status=400)
    data=form.cleaned_data;amount=(data['points']/100).quantize(Q8);greeting=data['greeting'] or '科研顺利！'
    if data['kind']=='transfer' and not peer: return JsonResponse({'error':'转账仅支持私聊。'},status=400)
    if peer and data['count']!=1: return JsonResponse({'error':'私聊红包只能发给当前成员，份数应为 1。'},status=400)
    if data['kind']=='transfer' and (data['count']!=1 or data['mode']!='equal'): return JsonResponse({'error':'转账参数无效。'},status=400)
    if int(amount/Q8)<data['count']: return JsonResponse({'error':'积分不足以分成这些份数。'},status=400)
    try:
        with transaction.atomic():
            config=writer_lock()
            existing=PointGift.objects.filter(pk=data['request_id']).select_related('message__author__member_profile').first()
            if existing:
                expected=(request.user.pk,peer.pk if peer else None,'private' if peer else key,data['kind'],data['mode'],amount,data['count'],greeting)
                actual=(existing.sender_id,existing.message.recipient_id,existing.message.room,existing.kind,existing.mode,existing.amount_cny,existing.count,existing.greeting)
                if expected!=actual: raise ValidationError('请求已变化，请刷新后重新发送。')
                return JsonResponse({'message':serialize(existing.message,request),'duplicate':True})
            require_member(request.user)
            if peer: require_member(peer)
            member=allowance(request.user);member.refresh_from_db()
            if not config.enabled or not member.enabled: raise ValidationError('你的积分转赠功能暂不可用。')
            updated=Allowance.objects.filter(pk=member.pk,extra_balance__gte=F('extra_reserved')+amount).update(extra_balance=F('extra_balance')-amount)
            if not updated: raise ValidationError('可转赠的额外点数不足；每周基础额度和调用中预留的点数不能转赠。')
            message=ChatMessage.objects.create(author=request.user,recipient=peer,room='private' if peer else key,body=('积分转账' if data['kind']=='transfer' else '积分红包')+' · '+greeting)
            PointGift.objects.create(id=data['request_id'],sender=request.user,message=message,kind=data['kind'],mode=data['mode'],
                amount_cny=amount,remaining_cny=amount,count=data['count'],greeting=greeting,expires_at=timezone.now()+timezone.timedelta(hours=24))
            return JsonResponse({'message':serialize(message,request)},status=201)
    except ValidationError as error: return JsonResponse({'error':' '.join(error.messages)},status=400)

@login_required
@never_cache
@require_http_methods(['GET','POST'])
def detail(request,pk):
    expire_gifts();gift=permitted_gift(request,pk)
    if request.method=='POST':
        if request.POST.get('action')!='refund' or request.POST.get('confirm')!='yes' or gift.sender_id!=request.user.pk or gift.kind!='transfer':
            return JsonResponse({'error':'只能退回自己发出的未领取转账。'},status=400)
        with transaction.atomic():
            writer_lock();gift=PointGift.objects.select_for_update().select_related('sender','message').get(pk=pk)
            refund_locked(gift)
    value=card(gift,request.user)
    value['receipts']=[{'username':r.user.username,'points':str(r.amount_cny*100),'at':r.created_at.isoformat()} for r in gift.receipts.select_related('user').order_by('pk')]
    return JsonResponse(value)

@login_required
@never_cache
@require_POST
def claim(request,pk):
    expire_gifts();gift=permitted_gift(request,pk)
    if request.POST.get('confirm')!='yes': return JsonResponse({'error':'请确认领取。'},status=400)
    try:
        with transaction.atomic():
            writer_lock();gift=PointGift.objects.select_for_update().select_related('sender','message').get(pk=pk)
            require_member(request.user)
            if gift.message.room=='private' and gift.message.recipient_id!=request.user.pk: raise PermissionDenied('只能由接收者领取。')
            receipt=PointGiftReceipt.objects.filter(gift=gift,user=request.user).first()
            if receipt: return JsonResponse(card(gift,request.user))
            if gift.closed_at or gift.expires_at<=timezone.now(): raise ValidationError('红包或转账已结束。')
            left=gift.count-gift.claimed_count;units=int(gift.remaining_cny/Q8)
            if left==1: amount=gift.remaining_cny
            elif gift.mode=='random': amount=Decimal(1+secrets.randbelow(min(units-left+1,max(1,2*units//left))))*Q8
            else:
                total=int(gift.amount_cny/Q8);base,remainder=divmod(total,gift.count)
                amount=Decimal(base+(1 if gift.claimed_count<remainder else 0))*Q8
            member=allowance(request.user)
            PointGiftReceipt.objects.create(gift=gift,user=request.user,amount_cny=amount)
            Allowance.objects.filter(pk=member.pk).update(extra_balance=F('extra_balance')+amount)
            gift.remaining_cny-=amount;gift.claimed_count+=1
            if gift.claimed_count==gift.count: gift.closed_at=timezone.now()
            gift.save(update_fields=['remaining_cny','claimed_count','closed_at'])
            return JsonResponse(card(gift,request.user))
    except ValidationError as error: return JsonResponse({'error':' '.join(error.messages)},status=400)

@login_required
@never_cache
@require_GET
def wallet(request):
    require_member(request.user);expire_gifts()
    from django.db.models import Q
    member=allowance(request.user)
    gifts=PointGift.objects.filter(Q(sender=request.user)|Q(receipts__user=request.user)).distinct().select_related('sender','message').prefetch_related(receipt_prefetch(request.user)).order_by('-created_at')[:50]
    return JsonResponse({'available_points':str(max(Decimal('0'),member.extra_balance-member.extra_reserved)*100),
                         'gifts':[card(gift,request.user) for gift in gifts]})
