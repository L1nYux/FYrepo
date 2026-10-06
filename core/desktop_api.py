"""Desktop clients use the same server sessions, users and invitations as the web UI.

Unlike the local preview bridge, these endpoints require normal Django CSRF checks.
There is no remote bootstrap administrator or token that bypasses account permissions.
"""
import hashlib
import json

from django.contrib.auth import login, logout
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect

from . import permissions as perms
from .forms import RegisterForm, RoleLoginForm
from .models import Invite, MemberProfile, UserPresence
from .identity import nickname, account_id


def reply(request, error=None, status=200):
    from aihub.permissions import is_pool_owner
    role = perms.account_role(request.user)
    authenticated = request.user.is_authenticated
    value = {'protocol': 1, 'authenticated': authenticated, 'requiresSetup': False,
             'username': request.user.username if authenticated else '',
             'nickname': nickname(request.user) if authenticated else '', 'accountId':account_id(request.user) if authenticated else '',
             'isAdmin': authenticated and role == perms.ADMIN,
             'canManageApi': authenticated and is_pool_owner(request), 'csrfToken': get_token(request)}
    if error:
        value['error'] = error
    value['hasEmail'] = bool(request.user.email.strip()) if authenticated else False
    value['teamId'] = getattr(getattr(request,'team',None),'pk',None)
    value['teamName'] = getattr(getattr(request,'team',None),'name','')
    value['needsTeam'] = authenticated and (not value['teamId'] or role == perms.NORMAL)
    from .team_permissions import can_manage_admission
    value['isPlatformAdmin'] = can_manage_admission(request)
    profile = getattr(request.user, 'member_profile', None) if authenticated else None
    value['mustChangePassword'] = bool(profile and profile.must_change_password)
    from .avatars import avatar_url
    value['avatarUrl'] = avatar_url(request.user) if authenticated else ''
    return JsonResponse(value, status=status)


@never_cache
@csrf_protect
def desktop_api(request, action):
    if action == 'status' and request.method == 'GET':
        # This changes layout only, in the desktop's separate cookie jar.
        if not request.session.get('desktop_client'):
            request.session['desktop_client'] = True
        return reply(request)
    if request.method != 'POST' or action not in ('login', 'register', 'logout'):
        return reply(request, '操作无效。', 405)
    if action == 'logout':
        if request.user.is_authenticated:
            UserPresence.objects.filter(user=request.user).delete()
        logout(request)
        request.session['desktop_client'] = True
        return reply(request)
    if request.user.is_authenticated and perms.account_role(request.user) not in (perms.ADMIN, perms.DEVELOPER):
        # A demoted account may still have a cookie. An explicit new login can
        # replace that session, without turning its old role into a permission.
        logout(request)
    if request.user.is_authenticated:
        return reply(request, '请先退出当前账户。', 409)
    try:
        if len(request.body) > 16000:
            raise ValueError
        data = json.loads(request.body)
        if not isinstance(data, dict) or any(not isinstance(v, str) or len(v) > 1000 for v in data.values()):
            raise ValueError
    except (ValueError, UnicodeDecodeError):
        return reply(request, '登录信息无效或过长。', 400)
    # A short-lived throttle, not an audit log. Deploy nginx rate limiting as well
    # so the limit also covers multiple application workers (see deployment guide).
    identity = request.META.get('REMOTE_ADDR', '') + '\0' + data.get('username', '').casefold()
    key = 'desktop-auth:' + hashlib.sha256(identity.encode()).hexdigest()
    attempts = cache.get(key, 0)
    if attempts >= 10:
        return reply(request, '尝试过于频繁，请一分钟后重试。', 429)
    cache.set(key, attempts + 1, 60)
    if action == 'login':
        form = RoleLoginForm(request, data={'username': data.get('username', ''), 'password': data.get('password', '')})
        if not form.is_valid():
            return reply(request, '工作台号或密码不正确，或账户已停用。', 400)
        user = form.get_user()
        from .tenancy import activate_request
        activate_request(request,user)
    else:
        from .account_registration import AccountForm
        from .admission import register_account
        from django.core.exceptions import ValidationError
        from .tenancy import activate_request
        form = AccountForm({'username': data.get('username', ''), 'email': data.get('email', ''), 'nickname':data.get('nickname',''),
                            'password1': data.get('password', ''), 'password2': data.get('passwordConfirm', ''),
                            'invite_code': data.get('inviteCode', ''), 'team_name': data.get('teamName', '')})
        if not form.is_valid():
            return reply(request, ' '.join(str(m) for group in form.errors.values() for m in group), 400)
        try:
            user, team = register_account(form)
        except (ValidationError, IntegrityError) as error:
            message = ' '.join(error.messages) if isinstance(error, ValidationError) else '工作台号、邮箱或邀请码已被使用。'
            return reply(request, message, 400)
        if team: request.session['workbench-team'] = team.pk
        activate_request(request, user)
    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    request.role = perms.account_role(user)
    request.session[perms.SESSION_KEY] = request.role
    request.session['desktop_client'] = True
    request.session.set_expiry(0 if data.get('remember') == '0' else 30 * 24 * 60 * 60)
    cache.delete(key)
    return reply(request)
