"""Session-bound mailbox verification; never change the mailbox before proof."""
import logging
from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.shortcuts import redirect
from django.template.loader import render_to_string
from django.utils import timezone
from .forms import normalise_email
from .models import EmailVerificationCode as Code

log = logging.getLogger(__name__)
SESSION_KEY = 'email-binding-challenge'


class MailboxForm(forms.Form):
    email = forms.EmailField(label='要绑定的邮箱', max_length=254,
        widget=forms.EmailInput(attrs={'autocomplete':'email', 'autocapitalize':'none',
                                      'spellcheck':'false', 'placeholder':'输入你自己的邮箱'}))

    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_email(self):
        value = normalise_email(self.cleaned_data['email'], self.user)
        if value == self.user.email:
            raise forms.ValidationError('这个邮箱已经绑定，无需重复验证。')
        return value


class MailboxCodeForm(forms.Form):
    code = forms.RegexField(r'^[0-9]{6}$', label='邮箱验证码',
        error_messages={'invalid':'请输入 6 位数字验证码。'},
        widget=forms.TextInput(attrs={'inputmode':'numeric', 'autocomplete':'one-time-code',
                                     'maxlength':6, 'placeholder':'6 位数字'}))


def process(request):
    """Return profile context and an optional redirect. Purpose and session isolate resets."""
    challenge = request.session.get(SESSION_KEY)
    item = None
    if isinstance(challenge, dict) and challenge.get('user') == request.user.pk:
        item = Code.objects.filter(pk=challenge.get('id'), user=request.user, purpose=Code.BIND).first()
        if not item or not item.is_usable or challenge.get('original') != request.user.email:
            item = None
            request.session.pop(SESSION_KEY, None)
    mailbox = MailboxForm(user=request.user, initial={'email':item.email if item else ''})
    code_form = MailboxCodeForm()
    action = request.POST.get('action') if request.method == 'POST' else None
    if action == 'email_cancel':
        if item:
            Code.objects.filter(pk=item.pk, used_at__isnull=True).update(used_at=timezone.now())
        request.session.pop(SESSION_KEY, None)
        return {}, redirect('profile')
    if action == 'email_send':
        mailbox = MailboxForm(request.POST, user=request.user)
        if mailbox.is_valid():
            with transaction.atomic():
                account = User.objects.select_for_update().get(pk=request.user.pk)
                cooldown = Code.cooldown_remaining(account, Code.BIND)
                if cooldown:
                    mailbox.add_error(None, f'请 {cooldown} 秒后再发送。')
                elif Code.sends_in_last_hour(account, Code.BIND) >= Code.MAX_SENDS_PER_HOUR:
                    mailbox.add_error(None, '发送过于频繁，请一小时后再试。')
                else:
                    sent, raw = Code.issue(account, mailbox.cleaned_data['email'], Code.BIND)
            if not mailbox.errors:
                try:
                    count = send_mail('科研工作台 · 绑定邮箱验证码',
                        render_to_string('core/email_binding_email.txt', {'user':account, 'code':raw}),
                        None, [sent.email], fail_silently=False)
                    if count != 1:
                        raise RuntimeError('email_not_sent')
                except Exception:
                    sent.consume()
                    item = None
                    request.session.pop(SESSION_KEY, None)
                    log.exception('邮箱绑定验证码发送失败')
                    mailbox.add_error(None, '邮件暂时未能发送，请稍后重试；原邮箱保持有效。')
                else:
                    request.session[SESSION_KEY] = {'id':sent.pk, 'user':account.pk, 'original':account.email}
                    messages.success(request, '验证码已发送，10 分钟内有效。请检查收件箱和垃圾邮件。'
                        if not settings.EMAIL_BACKEND.endswith('console.EmailBackend') else '开发模式：验证码仅输出到服务端控制台。')
                    return {}, redirect('profile')
    elif action == 'email_verify':
        code_form = MailboxCodeForm(request.POST)
        if code_form.is_valid():
            if not item:
                code_form.add_error(None, '验证码已失效，请重新发送。')
            else:
                try:
                    with transaction.atomic():
                        account = User.objects.select_for_update().get(pk=request.user.pk)
                        locked = Code.objects.select_for_update().get(pk=item.pk)
                        if account.email != challenge.get('original'):
                            code_form.add_error(None, '邮箱已在其他页面修改，请刷新后重试。')
                        elif not locked.verify(code_form.cleaned_data['code']):
                            code_form.add_error('code', '验证码不正确或已过期，请检查邮件。')
                        else:
                            account.email = normalise_email(locked.email, account)
                            account.save(update_fields=['email'])
                            locked.consume()
                            # Reset codes issued for an old mailbox must not remain usable.
                            Code.objects.filter(user=account, purpose=Code.RESET, used_at__isnull=True).update(used_at=locked.used_at)
                    if not code_form.errors:
                        request.session.pop(SESSION_KEY, None)
                        messages.success(request, '邮箱已验证并绑定，可用邮箱登录和找回密码。')
                        return {}, redirect('profile')
                except (IntegrityError, forms.ValidationError):
                    code_form.add_error(None, '该邮箱已被其他账号使用，请换一个邮箱。')
                item.refresh_from_db()
                if not item.is_usable:
                    request.session.pop(SESSION_KEY, None)
                    item = None
    return {'mailbox_form':mailbox, 'mailbox_code_form':code_form, 'binding_pending':item,
            'binding_cooldown':Code.cooldown_remaining(request.user, Code.BIND)}, None
