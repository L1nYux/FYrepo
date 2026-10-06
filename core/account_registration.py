from django.contrib.auth import login
from django.conf import settings
from django.shortcuts import redirect, render
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import IntegrityError
import hashlib
from .forms import RegisterForm
from .admission import register_account
from .tenancy import activate_request


class AccountForm(RegisterForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
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
        if form.is_valid():
            try:
                user,team=register_account(form)
            except (ValidationError, IntegrityError) as error:
                form.add_error(None,' '.join(error.messages) if isinstance(error,ValidationError) else '账户名、邮箱或邀请码已被使用，请重新填写。')
            else:
                if team: request.session['workbench-team']=team.pk
                login(request,user,backend='django.contrib.auth.backends.ModelBackend')
                activate_request(request,user)
                return redirect('workspace_home' if team else 'teams')
    return render(request,template,context)
