"""Stable login identifiers, public nicknames and optional team names."""
import re
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from .models import MemberProfile


def nickname(user):
    if not hasattr(user,'username'):return ''
    profile=getattr(user,'member_profile',None)
    return (profile.nickname if profile else '') or user.username


def default_id(user):
    value=user.username.lower()
    if re.fullmatch(r'[a-z][a-z0-9_-]{2,31}',value) and not User.objects.filter(username__iexact=value).exclude(pk=user.pk).exists() and not MemberProfile.objects.filter(workbench_id=value).exclude(user=user).exists():return value
    value='zy_'+str(user.pk).zfill(6)
    while User.objects.filter(username__iexact=value).exclude(pk=user.pk).exists() or MemberProfile.objects.filter(workbench_id=value).exclude(user=user).exists():value+='x'
    return value


def account_id(user):
    if not hasattr(user,'username'):return ''
    profile=getattr(user,'member_profile',None)
    return (profile.workbench_id if profile else '') or default_id(user)


def validate_id(value,user=None):
    value=value.strip().lower()
    if not re.fullmatch(r'[a-z][a-z0-9_-]{2,31}',value):raise ValidationError('工作台号需为 3–32 位字母、数字、下划线或短横线，以字母开头。')
    profiles=MemberProfile.objects.filter(workbench_id=value)
    users=User.objects.filter(username__iexact=value)
    if user:profiles=profiles.exclude(user=user);users=users.exclude(pk=user.pk)
    if profiles.exists() or users.exists():raise ValidationError('这个工作台号已被使用。')
    return value


def login_user(value):
    # Nickname and real name never participate in login resolution.
    value=value.strip()
    user=User.objects.filter(member_profile__workbench_id=value.lower()).first()
    if user:return user
    user=User.objects.filter(username__iexact=value).first()
    if not user:return None
    profile=getattr(user,'member_profile',None)
    if profile and profile.legacy_login_allowed:return user
    # Trusted command-line accounts can lack a profile. Accept their default
    # workbench ID, never an unrelated alias. Persisted profiles use only ID.
    if not profile and account_id(user)==value.lower():return user
    return None
