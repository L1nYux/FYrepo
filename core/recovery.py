"""One recovery page for signed-in and signed-out users, including phones."""
import hashlib
import logging
import time

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.mail import send_mail
from django.db import transaction
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from .models import EmailVerificationCode

log = logging.getLogger(__name__)
SESSION_KEY = 'email-recovery-challenge'


class IdentityForm(forms.Form):
    identity = forms.CharField(label='用户名或邮箱', max_length=254,
        widget=forms.TextInput(attrs={'autocomplete': 'username', 'autocapitalize': 'none',
                                     'spellcheck': 'false', 'placeholder': '输入账户名或已绑定的邮箱'}))


class RecoveryForm(SetPasswordForm):
    code = forms.RegexField(r'^[0-9]{6}$', label='邮箱验证码',
        error_messages={'invalid': '请输入 6 位数字验证码。'},
        widget=forms.TextInput(attrs={'inputmode': 'numeric', 'autocomplete': 'one-time-code',
                                     'maxlength': 6, 'placeholder': '6 位数字'}))
    field_order = ['code', 'new_password1', 'new_password2']


class RecoveryCodeForm(forms.Form):
    code = RecoveryForm.base_fields['code']


def _verify_challenge(request, challenge, raw):
    """Consume the code and grant a short-lived, password-version-bound reset ticket."""
    if not challenge or challenge.get('attempts',0)>=5:
        return False
    valid=False
    with transaction.atomic():
        item=EmailVerificationCode.objects.select_for_update().select_related('user').filter(
            pk=challenge.get('id'), purpose=EmailVerificationCode.RESET).first()
        valid=bool(item and item.user.is_active and item.user.has_usable_password()
            and item.email==item.user.email
            and (not request.user.is_authenticated or item.user_id==request.user.pk)
            and item.verify(raw))
        if valid:
            item.consume()
            challenge['verified']={'user':item.user_id, 'password':item.user.password, 'email':item.email}
    challenge['attempts']=challenge.get('attempts',0)+1
    request.session[SESSION_KEY]=challenge
    return valid


def _account(request, identity):
    if request.user.is_authenticated:
        return request.user
    user = User.objects.filter(username__iexact=identity).first()
    if user is None:
        matches = list(User.objects.filter(email__iexact=identity).exclude(email='')[:2])
        user = matches[0] if len(matches) == 1 else None
    return user if user and user.is_active and user.has_usable_password() and user.email.strip() else None


def _challenge(request):
    value = request.session.get(SESSION_KEY)
    if not isinstance(value, dict) or time.time() - value.get('issued', 0) >= 600:
        return None
    if value.get('owner') != (request.user.pk if request.user.is_authenticated else None):
        return None
    return value


@never_cache
@require_http_methods(['GET', 'POST'])
def recover(request):
    bound = request.user.is_authenticated
    no_email = bound and not request.user.email.strip()
    challenge = _challenge(request)
    identity_form = IdentityForm(initial={'identity': challenge.get('identity', '') if challenge else ''})
    password_form = RecoveryForm(request.user if bound else User())
    code_form = RecoveryCodeForm()
    if request.method == 'POST' and not no_email:
        action = request.POST.get('action')
        if action == 'send':
            identity_form = IdentityForm({'identity': request.user.username} if bound else request.POST)
            last_sent = request.session.get('email-recovery-last-sent', 0)
            remaining = max(0, int(60 - (time.time() - last_sent) + .999))
            if remaining:
                messages.error(request, f'请 {remaining} 秒后再发送。')
            elif identity_form.is_valid():
                identity = identity_form.cleaned_data['identity'].strip()
                throttle = 'recovery-send:' + hashlib.sha256(request.META.get('REMOTE_ADDR', '').encode()).hexdigest()
                if cache.get(throttle, 0) >= 20:
                    messages.error(request, '发送过于频繁，请稍后再试。')
                else:
                    cache.set(throttle, cache.get(throttle, 0) + 1, 3600)
                    user = _account(request, identity)
                    item = None
                    can_send = user and not EmailVerificationCode.cooldown_remaining(user) and EmailVerificationCode.sends_in_last_hour(user) < EmailVerificationCode.MAX_SENDS_PER_HOUR
                    failed = False
                    if can_send:
                        item, code = EmailVerificationCode.issue(user, user.email)
                        try:
                            send_mail('科研工作台 · 密码重置验证码', render_to_string('core/password_code_email.txt',
                                {'user': user, 'code': code, 'minutes': 10}), None, [user.email], fail_silently=False)
                        except Exception:
                            item.delete(); item = None; failed = True
                            log.exception('密码重置验证码发送失败')
                    # Unknown accounts and account throttles get exactly the same page.
                    # The server-side session binds the browser to its own latest challenge.
                    challenge = {'id': item.pk if item else None,
                                 'identity': identity, 'issued': time.time(), 'attempts': 0,
                                 'owner': request.user.pk if bound else None}
                    request.session[SESSION_KEY] = challenge
                    request.session['email-recovery-last-sent'] = time.time()
                    if settings.EMAIL_BACKEND.endswith('console.EmailBackend'):
                        messages.info(request, '开发模式未发送邮件；验证码已输出到服务端控制台。')
                    elif failed and bound:
                        messages.error(request, '邮件暂时未能发送，请稍后重试或联系管理员。')
                    else:
                        messages.success(request, '如果该账户已绑定可用邮箱，验证码将发送到该邮箱。请检查收件箱和垃圾邮件，10 分钟内有效。')
                    return redirect('password_reset')
        elif action == 'verify':
            code_form=RecoveryCodeForm(request.POST)
            if not challenge:
                code_form.add_error(None,'请先获取验证码；验证码过期后需重新发送。')
            elif code_form.is_valid():
                if _verify_challenge(request,challenge,code_form.cleaned_data['code']):
                    return redirect('password_reset')
                if challenge['attempts']>=5:
                    request.session.pop(SESSION_KEY,None);challenge=None
                    messages.error(request,'验证码已失效，请重新获取。')
                else:
                    code_form.add_error('code','验证码不正确或已过期，请检查邮件。')
        elif action == 'reset' and challenge and challenge.get('verified'):
            ticket=challenge['verified']
            with transaction.atomic():
                account=User.objects.select_for_update().filter(pk=ticket['user'],is_active=True).first()
                if (not account or account.password!=ticket['password'] or account.email!=ticket['email']
                    or bound and account.pk!=request.user.pk):
                    request.session.pop(SESSION_KEY,None);challenge=None
                    messages.error(request,'验证已失效，请重新获取验证码。')
                else:
                    password_form=SetPasswordForm(account,request.POST)
                    if password_form.is_valid():
                        password_form.save()
                        from .models import MemberProfile
                        MemberProfile.objects.filter(user=password_form.user).update(must_change_password=False, temporary_password_expires_at=None)
                        request.session.pop(SESSION_KEY,None)
                        if bound:update_session_auth_hash(request,password_form.user)
                        return render(request,'core/recovery.html',{'completed':True,'bound':bound})
        elif action == 'reset':
            challenge = _challenge(request)
            item = None
            if challenge and challenge.get('id'):
                item = EmailVerificationCode.objects.select_related('user').filter(pk=challenge['id']).first()
            # Do not expose account-specific password checks before the code is verified.
            password_form = RecoveryForm(User(), request.POST)
            if not challenge:
                messages.error(request, '请先获取验证码；验证码过期后需重新发送。')
            elif password_form.is_valid():
                valid = False
                with transaction.atomic():
                    if item:
                        item = EmailVerificationCode.objects.select_for_update().select_related('user').filter(pk=item.pk).first()
                        valid = (item is not None and item.purpose == EmailVerificationCode.RESET and item.user.is_active
                                 and item.user.has_usable_password() and item.email == item.user.email
                                 and (not bound or item.user_id == request.user.pk)
                                 and item.verify(password_form.cleaned_data['code']))
                    if valid:
                        account_form = RecoveryForm(item.user, request.POST)
                        if account_form.is_valid():
                            password_form = account_form
                            password_form.save()
                            from .models import MemberProfile
                            MemberProfile.objects.filter(user=password_form.user).update(must_change_password=False, temporary_password_expires_at=None)
                            item.consume()
                        else:
                            password_form = account_form
                            item.attempts -= 1
                            item.save(update_fields=['attempts'])
                            return render(request, 'core/recovery.html', {
                                'bound':bound,'identity_form':identity_form,'password_form':password_form,
                                'challenge':challenge, 'masked_email':f'{item.user.email[:1]}***@{item.user.email.partition("@")[2]}',
                                'email_console':settings.EMAIL_BACKEND.endswith('console.EmailBackend'),
                                'cooldown':max(0,int(60-(time.time()-request.session.get('email-recovery-last-sent',0))+.999))})
                if valid:
                    request.session.pop(SESSION_KEY, None)
                    if bound:
                        update_session_auth_hash(request, password_form.user)
                    return render(request, 'core/recovery.html', {'completed': True, 'bound': bound})
                challenge['attempts'] = challenge.get('attempts', 0) + 1
                if challenge['attempts'] >= 5 or item and not item.is_usable:
                    request.session.pop(SESSION_KEY, None); challenge = None
                    messages.error(request, '验证码已失效，请重新获取。')
                else:
                    request.session[SESSION_KEY] = challenge
                    password_form.add_error('code', '验证码不正确或已过期，请检查邮件。')
    local, _, domain = request.user.email.partition('@') if bound else ('', '', '')
    verified=bool(challenge and challenge.get('verified'))
    if verified and not password_form.is_bound:
        password_form=SetPasswordForm(request.user if bound else User())
    return render(request, 'core/recovery.html', {'bound': bound, 'no_email': no_email,
        'masked_email': f'{local[:1]}***@{domain}' if domain else '', 'identity_form': identity_form,
        'password_form': password_form, 'code_form':code_form, 'challenge': challenge, 'verified':verified,
        'email_console': settings.EMAIL_BACKEND.endswith('console.EmailBackend'),
        'cooldown': max(0, int(60 - (time.time() - request.session.get('email-recovery-last-sent', 0)) + .999))})


def legacy_code(request, **kwargs):
    return redirect('password_reset')
