"""登录身份中间件。

两件事：

1. 把「本次登录选择的身份」解析成生效角色，写进 `request.role`。
   生效角色永远不会高于账号自身的层级：账号被降级、或者会话里的身份过期时，
   这里会自动降回账号层级，不会留下越权的会话。
2. 普通用户的页面范围只留项目展示、公共聊天室、关于，以及账号自助（个人中心／改密／退出）。
   访问其它页面时直接跳回项目展示并提示，而不是丢一个 403。
"""

from django.contrib import messages
from django.shortcuts import redirect
from django.utils.deprecation import MiddlewareMixin

from . import permissions as perms

# 普通用户可以打开的视图名（按 URL name 判断，避免各处视图重复写装饰器）。
NORMAL_ALLOWED_VIEWS = frozenset({
    'platform_accounts','platform_reset_password',
    'personal_message_action','group_message_action','personal_message_file','personal_legacy_file','personal_thread_settings','personal_thread_history','group_thread_settings','group_thread_history','messages_team_rename','messages_team_transfer','messages_team_leave','messages_team_disband','messages_team_remove_member',
    'account_verify_registration','account_registration_code','account_close','account_export', 'messages_teams','messages_team_review','messages_team_members','messages_team_invites','messages_team_permissions','messages_team_recruitment','messages_unread', 'application_updates', 'application_update_detail', 'release_current', 'friend_search', 'messages_social', 'request_friend', 'friend_action', 'personal_chat', 'group_chat', 'group_manage', 'group_create', 'member_card',
    'team_square', 'team_listing', 'team_apply', 'applicant_resume', 'my_applications', 'team_application_action',
    'teams', 'team_create', 'team_switch', 'team_join', 'team_transfer', 'platform', 'account_register',
    'desktop_api', 'public_download', 'pool_models', 'pool_chat', 'pool_experiments', 'pool_experiment_run',  # Bearer API authenticates independently of the browser session.
    'showcase', 'about', 'chat',
    'chat_public', 'chat_public_messages',
    'profile', 'change_password', 'member_avatar',
    'login', 'logout', 'register',
    # 忘记密码是账号自助，普通用户同样需要能走完，否则点邮件里的链接会被弹回公开站。
    'password_reset', 'password_reset_done', 'password_reset_confirm', 'password_reset_complete',
    'password_code_reset', 'password_code_send', 'password_code_new_password',
    'public_home', 'public_projects', 'public_project_detail', 'public_experiments', 'public_experiment_detail', 'public_experiment_file', 'public_members', 'contact',
})

NORMAL_BLOCKED_MESSAGE = '当前是普通用户身份，只能查看项目展示、公共聊天室与关于页面。'

class LoginRoleMiddleware(MiddlewareMixin):
    def __call__(self, request):
        if self.async_mode:
            return self.scoped_async_call(request)
        from .tenancy import scope, activate_request
        from .workspace_audit import acting_as
        with scope(None, http=True):
            activate_request(request)
            with acting_as(request.user):
                return super().__call__(request)

    async def scoped_async_call(self, request):
        from asgiref.sync import sync_to_async
        from .tenancy import scope, activate_request
        from .workspace_audit import acting_as
        with scope(None, http=True):
            await sync_to_async(activate_request, thread_sensitive=True)(request)
            with acting_as(request.user):
                return await super().__acall__(request)

    def process_request(self, request):
        if request.user.is_authenticated:
            profile=getattr(request.user,'member_profile',None)
            version=profile.security_version if profile else 0
            previous=request.session.get('account-security-version')
            if not request.user.is_active or previous is None and version>0 or previous is not None and previous!=version:
                from django.contrib.auth import logout
                logout(request)
            else:request.session['account-security-version']=version
        account = perms.account_role(request.user)
        if account is None:
            request.role = None
            return None
        chosen = account
        if chosen not in perms.RANK or perms.RANK[chosen] > perms.RANK[account]:
            # 没选过身份，或所选身份已经超过账号层级（例如被降为开发者）：回到账号层级。
            chosen = account
            if request.session.get(perms.SESSION_KEY) != chosen:
                request.session[perms.SESSION_KEY] = chosen
        request.role = chosen
        return None

    def process_view(self, request, view_func, view_args, view_kwargs):
        match = request.resolver_match
        if match and request.GET.get('space'):
            from .message_scope import SCOPED_VIEWS, select
            if match.url_name in SCOPED_VIEWS:
                select(request, request.GET['space'], allow_guest=match.url_name in ('chat_public', 'chat_public_messages'))
        if match and match.namespace == 'admin':
            if not perms.is_platform_admin(request):
                from django.core.exceptions import PermissionDenied
                raise PermissionDenied('软件管理权限独立于团队管理员。')
            return None
        if request.user.is_authenticated:
            profile = getattr(request.user, 'member_profile', None)
            if profile and profile.must_change_password:
                from django.contrib.auth import logout
                from django.http import JsonResponse
                from django.utils import timezone
                name = match.url_name if match else ''
                if name not in ('logout', 'desktop_api', 'desktop_auth') and profile.temporary_password_expires_at and profile.temporary_password_expires_at <= timezone.now():
                    logout(request)
                    return redirect('login')
                if name not in ('required_password_change', 'logout', 'desktop_api', 'desktop_auth', 'member_avatar'):
                    if request.headers.get('Accept', '').startswith('application/json') or getattr(view_func, 'expects_json', False) or name in ('pool_models', 'pool_chat', 'pool_experiments', 'pool_experiment_run'):
                        return JsonResponse({'error': '请先设置新密码。', 'password_change_url': '/account/set-password/'}, status=403)
                    return redirect('required_password_change')
                if name == 'required_password_change':
                    return None
        if request.headers.get('Authorization', '').startswith('Bearer ') and match and match.url_name not in ('pool_models', 'pool_chat', 'pool_experiments', 'pool_experiment_run') and not request.user.is_authenticated:
            from django.http import JsonResponse
            return JsonResponse({'error': '个人 API Key 仅适用于 /api/pool/v1/；此页面需要登录会话。'}, status=401)
        if request.role != perms.NORMAL or (match and match.url_name == 'required_password_change'):
            return None
        match = request.resolver_match
        if match is None or match.url_name in NORMAL_ALLOWED_VIEWS:
            return None
        if getattr(view_func, 'expects_json', False):
            from django.http import JsonResponse
            return JsonResponse({'error': NORMAL_BLOCKED_MESSAGE}, status=403)
        if request.user.is_authenticated and request.team is None:
            return redirect('teams')
        messages.error(request, NORMAL_BLOCKED_MESSAGE)
        return redirect('showcase')
