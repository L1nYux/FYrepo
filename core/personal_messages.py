"""Personal friendships and private team groups; team colleagues are not automatic friends."""
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.contrib import messages
from django.db import transaction, IntegrityError
from django.db.models import Q, F
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from django.views.decorators.http import require_GET
from django.middleware.csrf import get_token
from django.utils import timezone
from datetime import timedelta
from .models import (TeamMembership, FriendRequest, Friendship, PersonalMessage, ChatGroup, GroupMember, GroupMessage)
from .tenancy import team_users
from . import permissions as perms
from .pagination import page
from .teams import valid_id
from .identity import nickname, account_id, login_user


def friends(user):
    relations=Friendship.objects.filter(Q(first=user)|Q(second=user))
    ids=set(relations.values_list('first_id',flat=True))|set(relations.values_list('second_id',flat=True))
    return User.objects.filter(pk__in=ids-{user.pk},is_active=True)


def permitted_peer(user,peer):
    pair=sorted([user.pk,peer.pk])
    if pair[0]==pair[1]: return False
    if Friendship.objects.filter(first_id=pair[0],second_id=pair[1]).exists(): return True
    teams=TeamMembership.objects.filter(user=user,active=True,deleted_at__isnull=True,team__active=True,role__in=['owner','admin','member']).values('team_id')
    return TeamMembership.objects.filter(user=peer,team_id__in=teams,active=True,deleted_at__isnull=True,role__in=['owner','admin','member']).exists()


@login_required
@never_cache
def index(request):
    colleague_ids=TeamMembership.objects.filter(user=request.user,active=True,deleted_at__isnull=True,team__active=True,role__in=['owner','admin','member']).values('team_id')
    colleagues=User.objects.filter(pk__in=TeamMembership.objects.filter(team_id__in=colleague_ids,active=True,deleted_at__isnull=True,role__in=['owner','admin','member']).values('user_id'),is_active=True).exclude(pk=request.user.pk).order_by('username')
    groups=ChatGroup.objects.filter(members__user=request.user,members__active=True,team__active=True,
        team__memberships__user=request.user,team__memberships__active=True,team__memberships__deleted_at__isnull=True,team__memberships__role__in=['owner','admin','member']).distinct().order_by('-created_at','-pk')
    return render(request,'core/social_inbox.html',{'friends':page(request,friends(request.user).order_by('username'),key='friends_page'),
        'colleagues':page(request,colleagues,key='colleagues_page'),'chat_groups':page(request,groups,key='groups_page'),
        'friend_requests':page(request,FriendRequest.objects.filter(recipient=request.user,state='pending').select_related('sender').order_by('-pk'),key='requests_page'),
        'selectable_members':team_users(member_only=True).exclude(pk=request.user.pk)[:1000] if perms.is_team_member(request) else []})


@login_required
@never_cache
@require_GET
def search_friend(request):
    name=request.GET.get('q','').strip()
    if not name or len(name)>150:return JsonResponse({'error':'请输入完整账号。'},status=400)
    peer=login_user(name)
    if peer and (not peer.is_active or peer.pk==request.user.pk):peer=None
    if not peer:return JsonResponse({'error':'没有找到该账号。'},status=404)
    from .models import PublicProfile
    profile=PublicProfile.objects.filter(user=peer,is_public=True).first()
    state='friends' if friends(request.user).filter(pk=peer.pk).exists() else 'sent' if FriendRequest.objects.filter(sender=request.user,recipient=peer,state='pending').exists() else 'none'
    return JsonResponse({'id':peer.pk,'username':account_id(peer),'display_name':nickname(peer),
        'friend_state':state,'friend_url':reverse('request_friend'),'csrf_token':get_token(request)})


@login_required
@require_POST
def request_friend(request):
    name=request.POST.get('username','').strip()[:150]
    peer=login_user(name)
    if peer and (not peer.is_active or peer.pk==request.user.pk):peer=None
    if not peer or friends(request.user).filter(pk=peer.pk).exists():
        messages.info(request,'账户不可申请或已是好友。');return JsonResponse({'error':'账户不可申请或已是好友。'},status=400) if request.headers.get('Accept')=='application/json' else redirect('messages_social')
    if FriendRequest.objects.filter(sender=request.user,created_at__gte=timezone.now()-timedelta(days=1)).count()>=20:
        messages.error(request,'今日好友申请已达上限。');return JsonResponse({'error':'今日好友申请已达上限。'},status=429) if request.headers.get('Accept')=='application/json' else redirect('messages_social')
    try:
        FriendRequest.objects.get_or_create(sender=request.user,recipient=peer,state='pending',defaults={'note':request.POST.get('note','').strip()[:200]})
    except IntegrityError: pass
    messages.success(request,'好友申请已发送，等待对方确认。')
    return JsonResponse({'state':'sent','message':'好友申请已发送，等待对方确认。'}) if request.headers.get('Accept')=='application/json' else redirect('messages_social')


@login_required
@require_POST
def friend_action(request,pk):
    action=request.POST.get('action')
    if action not in ('accept','reject'):raise PermissionDenied
    with transaction.atomic():
        FriendRequest.objects.filter(pk=pk,recipient=request.user,state='pending').update(state=F('state'))
        item=get_object_or_404(FriendRequest.objects.select_for_update(),pk=pk,recipient=request.user,state='pending')
        item.state='accepted' if action=='accept' else 'rejected';item.save(update_fields=['state'])
        if action=='accept':
            first,second=sorted([item.sender_id,item.recipient_id])
            Friendship.objects.get_or_create(first_id=first,second_id=second)
    return JsonResponse({'state':'friends' if action=='accept' else 'none'}) if request.headers.get('Accept')=='application/json' else redirect(reverse('messages_social')+'?tab=requests')


def body(request):
    text=request.POST.get('body','').strip()
    if not text or len(text)>2000:raise ValidationError('请输入 1–2000 字的消息。')
    return text


def stream(request, rows, create, title, action_url, group=None, peer=None):
    from .models import PersonalThreadRead
    def mark_read(cursor):
        if not cursor:return
        state,_=PersonalThreadRead.objects.get_or_create(user=request.user,channel='group:'+str(group.pk) if group else 'person:'+str(peer.pk))
        PersonalThreadRead.objects.filter(pk=state.pk,last_message_id__lt=cursor).update(last_message_id=cursor)
    json_response=request.headers.get('Accept')=='application/json'
    if json_response:
        try: after=int(request.GET.get('after','0'))
        except ValueError: return JsonResponse({'error':'消息游标无效。'},status=400)
        if not 0<=after<=9223372036854775807:
            return JsonResponse({'error':'消息游标无效。'},status=400)
    if request.method=='POST':
        try: create(body(request))
        except ValidationError as error:return JsonResponse({'error':' '.join(error.messages)},status=400)
        if not json_response:return redirect(action_url)
    if json_response:
        values=[{'id':item.pk,'author':nickname(getattr(item,'sender',getattr(item,'author',None))),
            'author_id':getattr(item,'sender_id',getattr(item,'author_id',None)),
            'mine':getattr(item,'sender_id',getattr(item,'author_id',None))==request.user.pk,
            'body':item.body,'at':timezone.localtime(item.created_at).strftime('%m-%d %H:%M')} for item in rows.filter(pk__gt=after).order_by('pk')[:100]]
        mark_read(values[-1]['id'] if values else 0)
        return JsonResponse({'messages':values})
    history=list(rows.order_by('-pk')[:100])[::-1]
    mark_read(history[-1].pk if history else 0)
    return render(request,'core/personal_thread.html',{'title':title,'thread_url':action_url,
        'chat_rows':history,'group':group,'can_manage_group':bool(group and (group.owner_id==request.user.pk or GroupMember.objects.filter(group=group,user=request.user,active=True,admin=True).exists()))})


@login_required
@never_cache
def personal(request,pk):
    peer=get_object_or_404(User,pk=pk,is_active=True)
    if not permitted_peer(request.user,peer):raise PermissionDenied('没有共同团队，请先添加好友。')
    rows=PersonalMessage.objects.filter(Q(sender=request.user,recipient=peer)|Q(sender=peer,recipient=request.user)).select_related('sender')
    return stream(request,rows,lambda text:PersonalMessage.objects.create(sender=request.user,recipient=peer,body=text),nickname(peer),reverse('personal_chat',args=[pk]),peer=peer)


def permitted_group(request,pk):
    group=get_object_or_404(ChatGroup.objects.select_related('team'),pk=pk,team__active=True)
    if not GroupMember.objects.filter(group=group,user=request.user,active=True).exists() or not TeamMembership.objects.filter(team=group.team,user=request.user,active=True,deleted_at__isnull=True,role__in=['owner','admin','member']).exists():
        raise PermissionDenied('无权访问这个团队群。')
    return group


@login_required
@never_cache
def group_chat(request,pk):
    group=permitted_group(request,pk)
    rows=GroupMessage.objects.filter(group=group).select_related('author')
    return stream(request,rows,lambda text:GroupMessage.objects.create(group=group,author=request.user,body=text),group.team.name+' · '+group.name,reverse('group_chat',args=[pk]),group)


@login_required
@require_POST
def create_group(request):
    if not perms.is_team_member(request):raise PermissionDenied
    name=request.POST.get('name','').strip()
    ids=request.POST.getlist('members')
    if not name or len(name)>80 or len(ids)>1000 or any(not value.isascii() or not value.isdigit() or len(value)>18 for value in ids):
        messages.error(request,'群名称或成员无效。');return redirect('messages_social')
    selected=set(map(int,ids))|{request.user.pk}
    members=team_users(member_only=True).filter(pk__in=selected)
    if members.count()!=len(selected):raise PermissionDenied('只能选择当前团队的在用成员。')
    with transaction.atomic():
        group=ChatGroup.objects.create(team=request.team,owner=request.user,name=name)
        GroupMember.objects.bulk_create([GroupMember(group=group,user=user,admin=user.pk==request.user.pk) for user in members])
    return redirect('group_chat',pk=group.pk)


@login_required
def manage_group(request,pk):
    group=permitted_group(request,pk)
    if not (group.owner_id==request.user.pk or GroupMember.objects.filter(group=group,user=request.user,active=True,admin=True).exists()):raise PermissionDenied
    if request.method=='POST':
        if not valid_id(request.POST.get('user','')): raise PermissionDenied
        user=get_object_or_404(User,pk=request.POST.get('user'))
        action=request.POST.get('action')
        if user.pk==group.owner_id:raise PermissionDenied('不能移除群主，请先交接。')
        if action=='add':
            if not TeamMembership.objects.filter(team=group.team,user=user,active=True,deleted_at__isnull=True,role__in=['owner','admin','member']).exists():raise PermissionDenied
            member,created=GroupMember.objects.get_or_create(group=group,user=user,defaults={'active':True,'admin':False})
            if not created and not GroupMember.objects.filter(pk=member.pk,active=False).update(active=True,admin=False):
                raise PermissionDenied('成员已在群内；任免群管理员须由群主操作。')
        elif action in ('remove','admin','member'):
            if action!='remove' and group.owner_id!=request.user.pk:raise PermissionDenied('仅群主可任免群管理员。')
            target=get_object_or_404(GroupMember,group=group,user=user,active=True)
            if target.admin and group.owner_id!=request.user.pk:raise PermissionDenied('群管理员不能移除其他管理员。')
            GroupMember.objects.filter(pk=target.pk).update(active=action!='remove',admin=action=='admin' or target.admin and action=='remove')
        else:raise PermissionDenied
        return redirect('group_manage',pk=pk)
    members=GroupMember.objects.filter(group=group,active=True).select_related('user').order_by('pk')
    available=User.objects.filter(pk__in=TeamMembership.objects.filter(team=group.team,active=True,deleted_at__isnull=True,role__in=['owner','admin','member']).values('user_id'),is_active=True).exclude(pk__in=members.values('user_id')).order_by('username')
    return render(request,'core/group_manage.html',{'group':group,'group_members':members,'available_members':available})
