from django.contrib.auth import login
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django import forms
from django.shortcuts import redirect, render
from django.core.cache import cache
from django.db import transaction, IntegrityError
import hashlib
from .forms import normalise_email
from .models import MemberProfile
from .tenancy import activate_request


class AccountForm(UserCreationForm):
    email=forms.EmailField(label='邮箱')
    class Meta(UserCreationForm.Meta):
        model=User
        fields=('username','email')

    def clean_email(self):return normalise_email(self.cleaned_data.get('email'))

    def clean_username(self):
        value=super().clean_username()
        if User.objects.filter(username__iexact=value).exists():raise forms.ValidationError('账户名已被使用。')
        return value


def register(request):
    if request.user.is_authenticated:return redirect('teams')
    form=AccountForm(request.POST or None)
    if request.method=='POST':
        key='account-register:'+hashlib.sha256(request.META.get('REMOTE_ADDR','').encode()).hexdigest()
        attempts=cache.get(key,0)
        if attempts>=10:
            form.add_error(None,'尝试过于频繁，请一分钟后重试。')
            return render(request,'core/account_register.html',{'form':form},status=429)
        cache.set(key,attempts+1,60)
    if request.method=='POST' and form.is_valid():
        try:
            with transaction.atomic():
                user=form.save()
                MemberProfile.objects.create(user=user,tier='normal')
        except IntegrityError:
            form.add_error(None,'账户名或邮箱已被使用，请重新填写。')
            return render(request,'core/account_register.html',{'form':form},status=400)
        login(request,user,backend='django.contrib.auth.backends.ModelBackend')
        activate_request(request,user)
        return redirect('teams')
    return render(request,'core/account_register.html',{'form':form})
