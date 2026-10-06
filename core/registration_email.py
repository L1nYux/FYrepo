"""Session-bound mailbox challenges shared by all application workers."""
import hashlib
import secrets
from datetime import timedelta
from django.core.mail import send_mail
from django.conf import settings
from django.contrib.auth.hashers import make_password, check_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from .forms import normalise_email
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from .models import RegistrationChallenge, RegistrationThrottle


def digest(value):return hashlib.sha256(value.encode()).hexdigest()


def send_code(request, email):
    if not settings.DEBUG and settings.EMAIL_BACKEND in ('django.core.mail.backends.console.EmailBackend','django.core.mail.backends.dummy.EmailBackend'):
        raise ValidationError('注册邮件尚未配置，请联系软件管理员。')
    email=normalise_email(email)
    validate_email(email)
    address=digest(request.META.get('REMOTE_ADDR',''))
    now=timezone.now()
    code=''.join(secrets.choice('0123456789') for _ in range(6))
    token=secrets.token_urlsafe(32)
    with transaction.atomic():
        RegistrationThrottle.objects.get_or_create(address_hash=address,defaults={'window_start':now})
        RegistrationThrottle.objects.filter(address_hash=address).update(count=F('count'))
        limit=RegistrationThrottle.objects.select_for_update().get(pk=address)
        if limit.window_start<now-timedelta(minutes=10):limit.window_start=now;limit.count=0
        if limit.count>=10:raise ValidationError('邮件发送过于频繁，请十分钟后再试。')
        if RegistrationChallenge.objects.filter(email=email,address_hash=address,created_at__gt=now-timedelta(seconds=60)).exists():raise ValidationError('请等待一分钟后再发送验证码。')
        limit.count+=1;limit.save()
        challenge=RegistrationChallenge.objects.create(token_hash=digest(token),address_hash=address,email=email,
            code_hash=make_password(code),expires_at=now+timedelta(minutes=10))
    try:
        delivered=send_mail('知域 · 注册邮箱验证',f'你的注册验证码是 {code}，10 分钟内有效。',settings.DEFAULT_FROM_EMAIL,[email],fail_silently=False)
        if delivered == 0:raise ValueError('mail backend did not send')
    except Exception:
        RegistrationChallenge.objects.filter(pk=challenge.pk).update(used_at=timezone.now())
        raise ValidationError('邮件发送失败，请稍后重试或联系软件管理员。')
    previous=request.session.get('signup-email-token')
    if previous:RegistrationChallenge.objects.filter(token_hash=digest(previous),used_at__isnull=True).update(used_at=now)
    request.session['signup-email-token']=token


def verify(request,email,code):
    error=None
    with transaction.atomic():
        token=digest(request.session.get('signup-email-token',''))
        RegistrationChallenge.objects.filter(token_hash=token).update(attempts=F('attempts'))
        item=RegistrationChallenge.objects.select_for_update().filter(token_hash=token,used_at__isnull=True).first()
        if not item or item.expires_at<=timezone.now() or item.attempts>=5 or item.email!=normalise_email(email):
            error='邮箱验证已失效，请重新发送验证码。'
        else:
            item.attempts+=1
            if not check_password(code.strip(),item.code_hash):error='邮箱验证码不正确。'
            else:item.used_at=timezone.now()
            item.save(update_fields=['attempts','used_at'])
    if error:raise ValidationError(error)
    request.session.pop('signup-email-token',None)
