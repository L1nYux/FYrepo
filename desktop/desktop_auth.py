"""Local-only desktop authentication, using the existing account and invitation rules."""
from core.team_permissions import can_manage_admission
from core.account_lifecycle import can_manage
import hashlib
import json
import os
import threading
import time
from pathlib import Path

from django.contrib.auth import login, logout
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import Http404, JsonResponse
from django.urls import path
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.views.decorators.csrf import csrf_exempt

from core import permissions as perms, middleware
from core.forms import RoleLoginForm, RegisterForm
from core.identity import nickname, account_id
from core.models import Invite, MemberProfile, UserPresence, Team, TeamMembership
from core.tenancy import activate_request

TOKEN = os.environ.pop('WORKBENCH_DESKTOP_BOOT_TOKEN')
MARKER = Path(os.environ['WORKBENCH_DESKTOP_STATE']) / 'server' / '.desktop-auth-ready'
middleware.NORMAL_ALLOWED_VIEWS = middleware.NORMAL_ALLOWED_VIEWS | {'desktop_auth'}
failed_logins = []
auth_lock = threading.Lock()


def needs_setup():
    if MARKER.exists():
        return False
    return not User.objects.exists() or (User.objects.count() == 1 and User.objects.filter(
        username='local-admin', is_active=True, is_staff=True).exists())


def session_info(request):
    from aihub.permissions import is_pool_owner
    setup = needs_setup()
    role = perms.account_role(request.user)
    authenticated = request.user.is_authenticated and not setup
    profile = getattr(request.user, 'member_profile', None) if authenticated else None
    return {'authenticated': authenticated, 'username': request.user.username if authenticated else '',
            'nickname': nickname(request.user) if authenticated else '', 'accountId': account_id(request.user) if authenticated else '',
            'isAdmin': role == perms.ADMIN if authenticated else False, 'canManageApi':is_pool_owner(request) if authenticated else False, 'requiresSetup': setup,
            'setupUsername': 'local-admin' if setup else '',
            'teamId': getattr(getattr(request, 'team', None), 'pk', None),
            'teamName': getattr(getattr(request, 'team', None), 'name', ''),
            'needsTeam': False,
            'spaceId':getattr(getattr(request,'workspace',None),'pk',None),
            'spaceKind':getattr(getattr(request,'workspace',None),'kind',''),
            'spaceName':getattr(getattr(request,'workspace',None),'name',''),
            'spaces':([{'id':'personal','name':'个人空间'}]+[{'id':str(m.team_id),'name':m.team.name} for m in TeamMembership.objects.filter(user=request.user,active=True,deleted_at__isnull=True,team__active=True,role__in=['owner','admin','member']).select_related('team')]) if authenticated else [],
            'isPlatformAdmin': can_manage_admission(request) or can_manage(request),
            'mustChangePassword': bool(profile and profile.must_change_password)}


def reply(value, status=200):
    response = JsonResponse(value, status=status)
    response['Cache-Control'] = 'no-store'
    return response


def form_error(form):
    return ' '.join(str(message) for messages in form.errors.values() for message in messages)


@csrf_exempt
def desktop_auth(request, action):
    # This per-run capability is only available to the trusted desktop process.
    if request.META.get('REMOTE_ADDR') != '127.0.0.1' or not constant_time_compare(
            request.headers.get('X-Desktop-Token', ''), TOKEN):
        raise Http404
    if action == 'status' and request.method == 'GET':
        return reply(session_info(request))
    if request.method != 'POST' or action not in ('login', 'logout', 'register', 'setup'):
        return reply({'error': '操作无效。'}, 405)
    if action == 'logout':
        if request.user.is_authenticated:
            UserPresence.objects.filter(user=request.user).delete()
        logout(request)
        return reply(session_info(request))
    try:
        if len(request.body) > 16000:
            return reply({'error': '登录信息过长。'}, 400)
        data = json.loads(request.body)
        if not isinstance(data, dict):
            raise ValueError
    except (ValueError, UnicodeDecodeError):
        return reply({'error': '登录信息无效。'}, 400)
    if any(not isinstance(value, str) or len(value) > 1000 for value in data.values()):
        return reply({'error': '登录信息无效或过长。'}, 400)
    with auth_lock:
        now = time.monotonic()
        failed_logins[:] = [stamp for stamp in failed_logins if now - stamp < 60]
        if len(failed_logins) >= 10:
            return reply({'error': '尝试过于频繁，请一分钟后重试。'}, 429)
        if action == 'setup':
            if not needs_setup():
                return reply({'error': '本地密码已设置，请直接登录。'}, 400)
            password = data.get('password', '')
            if password != data.get('passwordConfirm'):
                return reply({'error': '两次密码不一致。'}, 400)
            user = User.objects.filter(username='local-admin').first()
            candidate = user or User(username='local-admin', is_staff=True, is_superuser=True)
            try:
                validate_password(password, candidate)
            except ValidationError as error:
                return reply({'error': ' '.join(error.messages)}, 400)
            with transaction.atomic():
                if user is None:
                    user = User.objects.create_superuser('local-admin', password=password)
                else:
                    user.set_password(password)
                    user.save(update_fields=['password'])
                team = Team.objects.select_for_update().get(pk=1)
                if team.owner_id is None:
                    team.owner = user
                    team.save(update_fields=['owner'])
                TeamMembership.objects.update_or_create(team=team, user=user,
                    defaults={'role': 'owner' if team.owner_id == user.pk else 'admin', 'active': True, 'deleted_at': None})
                request.session['workbench-team'] = team.pk
                activate_request(request, user)
                from aihub.service import pool_settings
                pool=pool_settings()
                if pool.owner_id is None: pool.owner=user; pool.save(update_fields=['owner'])
            MARKER.write_text('ready', encoding='utf-8')
        elif action == 'login':
            if needs_setup():
                return reply({'error': '请先设置本地账户的登录密码。'}, 400)
            form = RoleLoginForm(request, data={'username': data.get('username', ''), 'password': data.get('password', '')})
            if not form.is_valid():
                failed_logins.append(now)
                return reply({'error': form_error(form)}, 400)
            user = form.get_user()
            activate_request(request, user)
        else:
            from core.account_registration import AccountForm
            from core.admission import register_account
            from django.core.exceptions import ValidationError
            form = AccountForm({'username': data.get('username', ''), 'email': data.get('email', ''), 'nickname': data.get('nickname', ''),
                                'password1': data.get('password', ''), 'password2': data.get('passwordConfirm', ''),
                                'email_code': data.get('emailCode', ''), 'invite_code': data.get('inviteCode', ''), 'team_name': data.get('teamName', '')})
            if not form.is_valid():
                return reply({'error': form_error(form)}, 400)
            try:
                from core.registration_email import verify
                verify(request, form.cleaned_data['email'], form.cleaned_data['email_code'])
                user, team = register_account(form)
            except (ValidationError, IntegrityError) as error:
                message = ' '.join(error.messages) if isinstance(error, ValidationError) else '工作台号、邮箱或邀请码已被使用。'
                return reply({'error': message}, 400)
            if team: request.session['workbench-team'] = team.pk
            activate_request(request, user)
        login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        request.session[perms.SESSION_KEY] = perms.account_role(user)
        request.session.set_expiry(0 if data.get('remember')=='0' else 30*24*60*60)
        failed_logins.clear()
        return reply(session_info(request))


urlpatterns = [path('_desktop/auth/<str:action>/', desktop_auth, name='desktop_auth')]
