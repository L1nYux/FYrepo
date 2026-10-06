from django.contrib.auth import login
from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect, render
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django import forms
from . import registration_email
import hashlib
from .forms import RegisterForm
from .admission import register_account
from .tenancy import activate_request


class AccountForm(RegisterForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email_code']=forms.CharField(label='邮箱验证码',max_length=6,required=False)
        self.fields['invite_code'].label='团队邀请码（可选）'
        self.fields['invite_code'].required = not getattr(settings, 'WORKBENCH_OPEN_REGISTRATION', False)


def register(request):
    if request.user.is_authenticated:
        return redirect('teams')
    form=AccountForm(request.POST or None)
    template='core/register.html' if request.resolver_match.url_name=='register' else 'core/account_register.html'
    context={'form':form,'auth_view':'register'}
    if request.method=='POST':
        key='account-register:'+hashlib.sha256(request.META.get('REMOTE_ADDR','').encode()).hexdigest()
        attempts=cache.get(key,0)
        if attempts>=10:
            form.add_error(None,'尝试过于频繁，请一分钟后重试。')
            return render(request,template,context,status=429)
        cache.set(key,attempts+1,60)
        if request.POST.get('action')=='send_code':
            try:registration_email.send_code(request,request.POST.get('email',''))
            except ValidationError as error:form.add_error(None,error)
            else:messages.success(request,'验证码已发送，10 分钟内有效。')
            return render(request,template,context)
        if form.is_valid():
            try:
                registration_email.verify(request,form.cleaned_data['email'],form.cleaned_data['email_code'])
                user,team=register_account(form)
            except (ValidationError, IntegrityError) as error:
                form.add_error(None,' '.join(error.messages) if isinstance(error,ValidationError) else '工作台号、邮箱或邀请码已被使用，请重新填写。')
            else:
                if team: request.session['workbench-team']=team.pk
                login(request,user,backend='django.contrib.auth.backends.ModelBackend')
                activate_request(request,user)
                return redirect('workspace_home')
    return render(request,template,context)
