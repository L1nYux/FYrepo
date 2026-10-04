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


def reply(request, error=None, status=200):
    from aihub.permissions import is_pool_owner
    role = perms.account_role(request.user)
    authenticated = request.user.is_authenticated and role in (perms.ADMIN, perms.DEVELOPER)
    value = {'protocol': 1, 'authenticated': authenticated, 'requiresSetup': False,
             'username': request.user.username if authenticated else '',
             'isAdmin': authenticated and role == perms.ADMIN,
             'canManageApi': authenticated and is_pool_owner(request), 'csrfToken': get_token(request)}
    if error:
        value['error'] = error
    value['hasEmail'] = bool(request.user.email.strip()) if authenticated else False
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
            return reply(request, '账户名或密码不正确，或账户已停用。', 400)
        user = form.get_user()
        if perms.account_role(user) not in (perms.ADMIN, perms.DEVELOPER):
            return reply(request, '桌面工作台仅供团队开发者和管理员使用。', 403)
    else:
        form = RegisterForm({'username': data.get('username', ''), 'email': data.get('email', ''),
                             'password1': data.get('password', ''), 'password2': data.get('passwordConfirm', ''),
                             'invite_code': data.get('inviteCode', '')})
        if not form.is_valid():
            return reply(request, ' '.join(str(m) for group in form.errors.values() for m in group), 400)
        digest = hashlib.sha256(form.cleaned_data['invite_code'].encode()).hexdigest()
        now = timezone.now()
        try:
            with transaction.atomic():
                invite = Invite.objects.filter(code_hash=digest, used_at__isnull=True,
                    revoked_at__isnull=True, expires_at__gt=now).first()
                if invite is None:
                    return reply(request, '邀请码无效、已使用或已过期。', 400)
                user = form.save(commit=False)
                user.is_staff = user.is_superuser = False
                user.save()
                MemberProfile.objects.update_or_create(user=user, defaults={'tier': MemberProfile.DEVELOPER})
                if Invite.objects.filter(pk=invite.pk, used_at__isnull=True,
                        revoked_at__isnull=True, expires_at__gt=now).update(used_by=user, used_at=now) != 1:
                    raise IntegrityError
        except IntegrityError:
            return reply(request, '账户名、邮箱或邀请码已被使用，请重新填写。', 400)
    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    request.role = perms.account_role(user)
    request.session[perms.SESSION_KEY] = request.role
    request.session['desktop_client'] = True
    request.session.set_expiry(0 if data.get('remember') == '0' else 30 * 24 * 60 * 60)
    cache.delete(key)
    return reply(request)
