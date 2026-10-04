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
    'desktop_api', 'public_download', 'pool_models', 'pool_chat', 'pool_experiments',  # Bearer API authenticates independently of the browser session.
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
    def process_request(self, request):
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
        if request.headers.get('Authorization', '').startswith('Bearer ') and match and match.url_name not in ('pool_models', 'pool_chat', 'pool_experiments') and not request.user.is_authenticated:
            from django.http import JsonResponse
            return JsonResponse({'error': '个人 API Key 仅适用于 /api/pool/v1/；此页面需要登录会话。'}, status=401)
        if request.role != perms.NORMAL:
            return None
        match = request.resolver_match
        if match is None or match.url_name in NORMAL_ALLOWED_VIEWS:
            return None
        if getattr(view_func, 'expects_json', False):
            from django.http import JsonResponse
            return JsonResponse({'error': NORMAL_BLOCKED_MESSAGE}, status=403)
        messages.error(request, NORMAL_BLOCKED_MESSAGE)
        return redirect('showcase')
