"""Session-bound, short-lived QR login with explicit approval on the phone."""
import hashlib
import hmac
import json
import secrets
from datetime import timedelta
from io import BytesIO
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse, HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods
from .models import ScanLoginChallenge
from . import permissions as perms


def digest(value):return hashlib.sha256(value.encode()).hexdigest()


@never_cache
@require_http_methods(['GET','POST'])
def challenge(request):
    if not request.session.session_key:request.session.create()
    get_token(request)
    binding=digest(request.session.session_key)
    if request.method=='GET':
        return JsonResponse({'csrf_token':get_token(request)})
    try:data=json.loads(request.body) if request.content_type=='application/json' else request.POST
    except ValueError:return JsonResponse({'error':'请求无效。'},status=400)
    action=data.get('action','create')
    if action=='create':
        if request.user.is_authenticated:return JsonResponse({'error':'当前设备已经登录。'},status=400)
        key='scan-login-rate:'+digest(request.META.get('REMOTE_ADDR',''))
        attempts=cache.get(key,0)
        if attempts>=20:return JsonResponse({'error':'请求过于频繁，请稍后重试。'},status=429)
        cache.set(key,attempts+1,60)
        ScanLoginChallenge.objects.filter(consumed_at__isnull=True,expires_at__lt=timezone.now()-timedelta(days=1)).delete()
        ScanLoginChallenge.objects.filter(session_hash=binding,consumed_at__isnull=True).update(expires_at=timezone.now())
        token=secrets.token_urlsafe(32)
        item=ScanLoginChallenge.objects.create(token_hash=digest(token),session_hash=binding,device=str(data.get('device','电脑'))[:100],expires_at=timezone.now()+timedelta(minutes=2))
        url=request.build_absolute_uri('/app/scan-login/'+str(item.pk)+'/?token='+token)
        import qrcode
        import qrcode.image.svg
        qr=qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=8, border=4)
        qr.add_data(url); qr.make(fit=True)
        image=qr.make_image(image_factory=qrcode.image.svg.SvgPathImage)
        buffer=BytesIO();image.save(buffer)
        from xml.etree import ElementTree as ET
        from django.templatetags.static import static
        ET.register_namespace('', 'http://www.w3.org/2000/svg')
        svg=ET.fromstring(buffer.getvalue())
        width=float(svg.attrib['viewBox'].split()[2]); size=width*.19; padding=width*.025
        ns='{http://www.w3.org/2000/svg}'
        ET.SubElement(svg,ns+'rect',{'x':str((width-size)/2-padding),'y':str((width-size)/2-padding),
            'width':str(size+2*padding),'height':str(size+2*padding),'rx':str(padding),'fill':'white'})
        ET.SubElement(svg,ns+'image',{'href':request.build_absolute_uri(static('core/team-logo.png')),'x':str((width-size)/2),
            'y':str((width-size)/2),'width':str(size),'height':str(size),'preserveAspectRatio':'xMidYMid meet'})
        return JsonResponse({'id':str(item.pk),'qr_svg':ET.tostring(svg,encoding='unicode'),'expires_in':120,'state':'waiting'})
    try:pk=str(data.get('id',''));item=ScanLoginChallenge.objects.filter(pk=pk,session_hash=binding).first()
    except (ValueError,TypeError,ValidationError):item=None
    if not item:return JsonResponse({'error':'登录请求不可用。'},status=404)
    if action=='cancel':
        ScanLoginChallenge.objects.filter(pk=item.pk,session_hash=binding).update(expires_at=timezone.now())
        return JsonResponse({'state':'cancelled'})
    if action not in ('poll','consume'):return JsonResponse({'error':'操作无效。'},status=400)
    if item.expires_at<=timezone.now() or item.consumed_at:return JsonResponse({'state':'expired'})
    if not item.confirmed_at:return JsonResponse({'state':'waiting'})
    if action=='poll':return JsonResponse({'state':'confirmed'})
    with transaction.atomic():
        # Acquire the write lock first on SQLite; conditional consumption also
        # protects against a second worker attempting to reuse the challenge.
        won=ScanLoginChallenge.objects.filter(pk=item.pk,session_hash=binding,consumed_at__isnull=True,expires_at__gt=timezone.now(),confirmed_at__isnull=False,user__is_active=True).update(consumed_at=timezone.now())
        if not won:return JsonResponse({'state':'expired'})
        item.refresh_from_db()
        user=item.user
        from .tenancy import activate_request
        activate_request(request,user)
        login(request,user,backend='django.contrib.auth.backends.ModelBackend')
        request.role=perms.account_role(user);request.session[perms.SESSION_KEY]=request.role
        request.session['account-security-version']=getattr(getattr(user,'member_profile',None),'security_version',0)
        request.session['desktop_client']=True;request.session.set_expiry(30*86400)
        request.session.save()
        # Keep the concrete device session for phone-side revocation.
        item.session_hash='session:'+request.session.session_key;item.save(update_fields=['session_hash'])
    from .desktop_api import reply
    return reply(request)


@login_required
@never_cache
@require_http_methods(['GET','POST'])
def confirm(request,pk):
    item=get_object_or_404(ScanLoginChallenge,pk=pk)
    token=request.POST.get('token') or request.GET.get('token','')
    valid=hmac.compare_digest(item.token_hash,digest(token)) and item.expires_at>timezone.now() and not item.consumed_at
    status='expired' if not valid else 'confirmed' if item.confirmed_at else 'waiting'
    if request.method=='POST' and valid:
        if request.POST.get('action')=='approve':
            changed=ScanLoginChallenge.objects.filter(pk=pk,confirmed_at__isnull=True,consumed_at__isnull=True,expires_at__gt=timezone.now()).update(user=request.user,confirmed_at=timezone.now())
            status='confirmed' if changed else 'expired'
        elif request.POST.get('action')=='cancel':
            ScanLoginChallenge.objects.filter(pk=pk,consumed_at__isnull=True).update(expires_at=timezone.now());status='cancelled'
    return render(request,'core/scan_login.html',{'challenge':item,'token':token,'scan_state':status})


@login_required
@never_cache
@require_http_methods(['GET','POST'])
def devices(request):
    rows=ScanLoginChallenge.objects.filter(user=request.user,consumed_at__isnull=False,session_hash__startswith='session:').order_by('-consumed_at')
    if request.method=='POST':
        try:item=get_object_or_404(rows,pk=request.POST.get('id'))
        except (ValidationError,ValueError,TypeError):return JsonResponse({'error':'设备无效。'},status=400)
        Session.objects.filter(session_key=item.session_hash[8:]).delete()
        item.session_hash='revoked';item.save(update_fields=['session_hash'])
    active=[r for r in rows[:30] if Session.objects.filter(session_key=r.session_hash[8:],expire_date__gt=timezone.now()).exists()]
    return render(request,'core/scan_devices.html',{'devices':active})


def register_device(request,label):
    if not request.user.is_authenticated or not request.session.session_key:return
    now=timezone.now()
    ScanLoginChallenge.objects.get_or_create(user=request.user,session_hash='session:'+request.session.session_key,
        defaults={'token_hash':digest(secrets.token_urlsafe(32)),'device':label,'expires_at':now,'confirmed_at':now,'consumed_at':now})
