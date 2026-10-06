"""工作台视图。

页面分工：
- 公开站（`core/portal.py`）：访客无需登录即可看项目概览、公开实验及其附件、成员公开资料，
  以及团队联系方式。本模块只负责工作台内部页面。
- 聊天室：历史入口。房间标签为「公共讨论」（管理员＋开发者）与「公共聊天室」（所有登录用户），
  轮询拉新消息；日常沟通已迁移到 `core/messages.py` 的消息中心。
- 工作台首页：项目总览（项目进度、未结项任务数），可按「与我有关」过滤。
- 项目页：目标、成员、预算与成本汇总、任务树（母任务／子任务）、最新成果与留言。
- 任务页：说明、进度、子任务、成果与审核、留言。
- 个人中心：账号资料与修改密码两栏，以及角色权限清单；主题开关在顶栏，不在这一页。
- 财务：账本与报销合并为一页（报销区在前，账本在后），仅管理员可记账、作废与审批；
  账本余额与合计按整本账本聚合，不随列表显示条数变化。
- 人员：邀请码与成员任免（仅管理员）。
- 深色模式：由浏览器偏好与本地设置决定，不需要登录状态（见 static/core/site.js）。

角色由 core/permissions.py 统一判定，生效角色来自登录时选择的身份（见 core/middleware.py）：

- 管理员登录：完整界面。
- 开发者登录：没有后台入口、没有全局审核、看不到邀请码。
- 普通用户登录：只能看公开站、公共聊天室与个人中心，其余页面由中间件跳回公开站。

工作台与消息区的页面都要求登录；公开站与公开附件例外，访客可访问。
"""

import hashlib
import logging
from decimal import Decimal

from .avatars import avatar_url
from .messages import visible_messages
from .pagination import page
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm
from django.contrib.auth.models import User
from django.contrib.auth.views import (LoginView, LogoutView, PasswordResetCompleteView,
                                      PasswordResetConfirmView, PasswordResetDoneView,
                                      PasswordResetView)
from django.core.exceptions import PermissionDenied
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Sum
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.decorators.cache import never_cache

from . import permissions as perms
from .navigation import workspace_return_path
from .forms import (ChatMessageForm, ClaimForm, CommentForm, FinalForm, FinanceForm,
                    ProfileForm, ProgressForm, ProjectForm, RegisterForm,
                    ReviewForm, RoleLoginForm, SubmissionForm, TaskForm, ExperimentForm)
from .models import (Attachment, ChatMessage, Comment, EmailVerificationCode, ExpenseClaim,
                     FinanceEntry, Invite, Experiment, MemberProfile, OUTFLOW_KINDS, Project, Submission, Task,
                     ExperimentTemplate, attach_files, summarise_progress)

logger = logging.getLogger(__name__)


def _role_home(user=None, role=None):
    """该身份登录后应该落在哪个页面。"""
    return perms.home_url_name(role or perms.account_role(user))



def _visible_project(request, pk):
    return get_object_or_404(Project.objects.select_related('owner', 'created_by'),
                             pk=pk, archived_at__isnull=True)


def _visible_task(request, pk):
    return get_object_or_404(
        Task.objects.select_related('project', 'project__owner', 'parent', 'assignee', 'created_by'),
        pk=pk, archived_at__isnull=True, project__archived_at__isnull=True, parent__archived_at__isnull=True)


def _back_to(request, fallback, **kwargs):
    """操作后回到工作台内的来源页面，否则回退到指定页面。"""
    target = workspace_return_path(request.POST.get('next'))
    if target:
        return redirect(target)
    return redirect(fallback, **kwargs)


def money(value):
    """把金额聚合结果补齐到「分」。SQLite 的 SUM 会丢掉小数尾零（10000.00 → 10000）。"""
    return (value or Decimal('0')).quantize(Decimal('0.01'))


def project_cost(project, limit=20):
    """项目成本汇总：关联本项目的未作废账目，按流出／流入分别合计。

    已用 = 流出类账目合计；项目收入 = 其余类型合计；预算剩余 = 预算 − 已用。
    未设预算（或预算为 0）时不给剩余与使用比例，避免除零和误导。
    """
    linked = FinanceEntry.objects.filter(project=project, voided_at__isnull=True, archived_at__isnull=True)
    totals = linked.aggregate(
        spent=Sum('amount', filter=Q(kind__in=OUTFLOW_KINDS), default=Decimal('0')),
        received=Sum('amount', filter=~Q(kind__in=OUTFLOW_KINDS), default=Decimal('0')),
    )
    spent, received = money(totals['spent']), money(totals['received'])
    budget = project.budget
    remaining = usage = bar = None
    if budget:
        remaining = money(budget - spent)
        usage = round(spent / budget * 100)
        bar = min(max(usage, 0), 100)
    return {
        'cost_entries': list(linked.select_related('created_by').order_by('-occurred_on', '-created_at', '-pk')[:limit]),
        'cost_spent': spent,
        'cost_received': received,
        'cost_net': money(spent - received),
        'cost_budget': budget,
        'cost_remaining': remaining,
        'cost_usage': usage,
        'cost_bar': bar,
    }


def _submission_back(request, submission):
    """成果挂在任务或项目上，返回的页面不同。"""
    if submission.task_id:
        return _back_to(request, 'task_detail', pk=submission.task_id)
    return _back_to(request, 'project_detail', pk=submission.project_id)


def _sync_task_status(task, reviewer):
    """审核后同步任务状态：还有待审核就停在「待审核」，都审完了按结果结项或回到进行中。"""
    pending = task.submissions.filter(status=Submission.PENDING).exists()
    accepted = task.submissions.filter(status=Submission.ACCEPTED).exists()
    fields = ['status', 'updated_at']
    if pending:
        task.status = Task.SUBMITTED
    elif accepted:
        task.status = Task.COMPLETED
        task.progress = 100
        task.closed_at = timezone.now()
        task.closed_by = reviewer
        fields += ['progress', 'closed_at', 'closed_by']
    else:
        task.status = Task.OPEN
        task.closed_at = None
        task.closed_by = None
        fields += ['closed_at', 'closed_by']
    task.save(update_fields=fields)


# --------------------------------------------------------------------------
# 账号
# --------------------------------------------------------------------------

class RoleLoginView(LoginView):
    """登录：账户名（或邮箱）+ 密码。生效角色恒取账号自身层级，用户不再选身份。"""

    template_name = 'core/login.html'
    form_class = RoleLoginForm

    def get_success_url(self):
        if not getattr(self.request,'team',None): return reverse('teams')
        # form_valid() 里已经校验过身份，这里直接用；兜底再读一次会话。
        role = getattr(self, 'role', None) or self.request.session.get(perms.SESSION_KEY)
        return reverse(perms.home_url_name(role))

    def form_valid(self, form):
        user = form.get_user()
        from .tenancy import activate_request
        activate_request(self.request,user)
        role = perms.account_role(user)
        if not perms.can_login_as(user, role):
            # 非字段错误：RoleLoginForm 没有 role 字段，写字段错误会直接抛 ValueError。
            form.add_error(None, perms.role_error(user, role))
            return self.form_invalid(form)
        self.role = role  # 必须在 super() 之前，get_success_url() 会用到。
        response = super().form_valid(form)
        self.request.session[perms.SESSION_KEY] = role
        self.request.session.set_expiry(30*24*60*60 if form.cleaned_data.get('remember') else 0)
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['auth_view'] = 'login'
        return context


def register(request):
    """开发者注册：必须持管理员发放的一次性邀请码。"""
    if request.user.is_authenticated:
        return redirect(_role_home(role=request.role))
    form = RegisterForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        digest = hashlib.sha256(form.cleaned_data['invite_code'].encode()).hexdigest()
        now = timezone.now()
        try:
            with transaction.atomic():
                invite = Invite.all_objects.filter(code_hash=digest, used_at__isnull=True,team__active=True,
                                               revoked_at__isnull=True, expires_at__gt=now).first()
                if invite is None:
                    form.add_error('invite_code', '邀请码无效、已使用或已过期。')
                else:
                    user = form.save(commit=False)
                    user.is_staff = False
                    user.is_superuser = False
                    user.save()
                    MemberProfile.objects.update_or_create(user=user, defaults={'tier': MemberProfile.DEVELOPER})
                    from .models import TeamMembership
                    from .tenancy import activate_request
                    TeamMembership.objects.create(team_id=invite.team_id,user=user,role='member')
                    request.session['workbench-team']=invite.team_id
                    activate_request(request,user)
                    changed = Invite.objects.filter(pk=invite.pk, used_at__isnull=True,
                                                    revoked_at__isnull=True, expires_at__gt=now).update(
                        used_by=user, used_at=now)
                    if changed != 1:
                        raise IntegrityError('邀请码已被使用')
                    login(request, user)
                    request.session[perms.SESSION_KEY] = perms.DEVELOPER
                    return redirect('workspace_home')
        except IntegrityError:
            form.add_error('invite_code', '邀请码已被使用，请联系管理员。')
    return render(request, 'core/register.html', {'form': form, 'auth_view': 'register'})


# --------------------------------------------------------------------------
# 忘记密码：邮箱自助找回
#
# 直接复用 Django 自带的重置流程（表单、令牌、密码强度校验都不自己写）：
# - 令牌由 `default_token_generator` 生成，哈希里含密码与邮箱，改密或改邮箱后旧链接立即失效；
# - 有效期取 `PASSWORD_RESET_TIMEOUT`（默认 1 小时，见 config/settings.py）；
# - `PasswordResetConfirmView.post_reset_login` 保持 False：重置完要用户自己用新密码登录，
#   同时 Django 会换掉密码哈希，该账号在其他设备上的旧会话随之失效。
#
# 邮件发送依赖 SMTP：DEBUG 下是控制台后端，重置链接直接打印在 runserver 输出里。
# --------------------------------------------------------------------------

class ForgotPasswordView(PasswordResetView):
    """第一步：填邮箱。邮箱不存在时同样跳到「已发送」页，不暴露账号是否存在。"""

    template_name = 'core/password_reset_form.html'
    email_template_name = 'core/password_reset_email.txt'
    subject_template_name = 'core/password_reset_subject.txt'
    success_url = reverse_lazy('password_reset_done')

    def form_valid(self, form):
        """发信失败时不要让成员看到 500：给出可执行的提示，并保留原表单。"""
        try:
            return super().form_valid(form)
        except Exception:
            logger.exception('重置邮件发送失败')
            form.add_error(None, '重置邮件发送失败：服务器的邮件配置可能有问题，'
                                 '请联系管理员检查 SMTP 设置。')
            return self.form_invalid(form)


class ForgotPasswordDoneView(PasswordResetDoneView):
    template_name = 'core/password_reset_done.html'


class ResetPasswordConfirmView(PasswordResetConfirmView):
    """第二步：从邮件链接进来设置新密码；链接无效或过期时同一模板给出提示。"""

    template_name = 'core/password_reset_confirm.html'

    def form_valid(self, form):
        with transaction.atomic():
            response = super().form_valid(form)
            MemberProfile.objects.filter(user=form.user).update(must_change_password=False, temporary_password_expires_at=None)
        return response

    success_url = reverse_lazy('password_reset_complete')


class ResetPasswordCompleteView(PasswordResetCompleteView):
    template_name = 'core/password_reset_complete.html'


# --------------------------------------------------------------------------
# 账户设置里的「忘记密码」：邮箱验证码验证身份后重置
#
# 与上面那条链接流程的分工：
# - 登录页「忘记密码」→ 邮件里的重置链接，用于**进不来**的情况；
# - 已登录时的「忘记密码」→ 邮箱验证码，用于**已经进来、只是不记得旧密码**的情况，
#   免去「修改密码要先填旧密码」的死循环。
#
# 因为这里已经有登录会话，验证码是在会话之上再确认一次邮箱归属，风险面比匿名流程小：
# 猜验证码的前提是已经拿到该账号的会话。即便如此，仍做了摘要存储、限次、限频、过期与单次使用。
# --------------------------------------------------------------------------

def email_goes_to_console():
    """当前是否在用控制台邮件后端：本地调试时验证码/链接只打印到控制台，不会真的发邮件。"""
    return settings.EMAIL_BACKEND.endswith('console.EmailBackend')


# 会话键：第一段验证码校验通过后，记下是哪条验证码，第二步据此放行。
CODE_VERIFIED_SESSION_KEY = 'workbench-password-code-verified'


def _code_verified_id(request):
    """第一步验证通过的那条验证码主键（存在会话里）；没有或不合法返回 None。"""
    data = request.session.get(CODE_VERIFIED_SESSION_KEY)
    return data.get('code') if isinstance(data, dict) else None


def _mask_email(email):
    """只显示首字符与域名，避免在页面上完整回显邮箱。"""
    local, _, domain = (email or '').partition('@')
    return f'{local[:1]}***@{domain}' if domain else '已绑定邮箱'


@login_required
@require_POST
def password_code_send(request):
    """把验证码发到账号自己绑定的邮箱。"""
    user = request.user
    email = (user.email or '').strip()
    if not email:
        messages.error(request, '账号还没有填邮箱，请先在「账户资料」填写并保存后再用验证码重置。')
        return redirect('password_code_reset')

    remaining = EmailVerificationCode.cooldown_remaining(user)
    if remaining:
        messages.error(request, f'验证码刚刚发过了，请 {remaining} 秒后再试。')
        return redirect('password_code_reset')
    if EmailVerificationCode.sends_in_last_hour(user) >= EmailVerificationCode.MAX_SENDS_PER_HOUR:
        messages.error(request, '一小时内发送次数过多，请稍后再试，或联系管理员。')
        return redirect('password_code_reset')

    item, code = EmailVerificationCode.issue(user, email)
    try:
        send_mail(
            render_to_string('core/password_code_subject.txt').strip(),
            render_to_string('core/password_code_email.txt', {
                'user': user, 'code': code, 'minutes': EmailVerificationCode.TTL_MINUTES}),
            None,  # from_email=None 时使用 DEFAULT_FROM_EMAIL
            [email],
            fail_silently=False,
        )
    except Exception:
        # 没发出去就不该算数：删掉这条验证码，免得白占 60 秒冷却和一小时配额。
        logger.exception('验证码发送失败（收件人 %s）', _mask_email(email))
        item.delete()
        messages.error(request, '验证码发送失败：服务器的邮件配置可能有问题，'
                                '请联系管理员检查 SMTP 设置；也可以请管理员协助重置密码。')
        return redirect('password_code_reset')

    if email_goes_to_console():
        messages.success(request, '开发模式：验证码不会真的发邮件，已打印在 runserver 的控制台输出里。')
    else:
        messages.success(request, f'验证码已发送到 {_mask_email(email)}，'
                                  f'{EmailVerificationCode.TTL_MINUTES} 分钟内有效。')
    return redirect('password_code_reset')


@login_required
def password_code_reset(request):
    """第一步：获取并输入验证码。校验通过后才进入第二步设置新密码。

    校验通过的事实记在会话里（绑定这条验证码的主键），第二步据此放行：
    换了新验证码、验证码过期或作废、清掉会话，都会退回这一步重新验证。
    """
    item = EmailVerificationCode.latest_usable(request.user)
    if request.method == 'POST':
        code = (request.POST.get('code') or '').strip()
        if item is None or not item.is_usable:
            messages.error(request, f'请先获取验证码（验证码 {EmailVerificationCode.TTL_MINUTES} 分钟内有效）。')
        elif not item.verify(code):
            if item.attempts >= EmailVerificationCode.MAX_ATTEMPTS:
                messages.error(request, '验证码错误次数过多，已作废，请重新获取。')
            else:
                left = EmailVerificationCode.MAX_ATTEMPTS - item.attempts
                messages.error(request, f'验证码不正确或已过期，还可以尝试 {left} 次。')
        else:
            request.session[CODE_VERIFIED_SESSION_KEY] = {'code': item.pk}
            return redirect('password_code_new_password')
    return render(request, 'core/password_code_reset.html', {
        'code_ttl': EmailVerificationCode.TTL_MINUTES,
        'has_email': bool((request.user.email or '').strip()),
        'masked_email': _mask_email(request.user.email),
        'cooldown': EmailVerificationCode.cooldown_remaining(request.user),
        'verified': _code_verified_id(request) == (item.pk if item else None),
    })


@login_required
def password_code_new_password(request):
    """第二步：设置新密码。没有通过第一步的验证码校验就退回第一步。"""
    item = EmailVerificationCode.latest_usable(request.user)
    if item is None or not item.is_usable or _code_verified_id(request) != item.pk:
        messages.error(request, '请先输入邮箱验证码完成验证。')
        return redirect('password_code_reset')

    form = SetPasswordForm(request.user, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            form.save()
            item.consume()
        request.session.pop(CODE_VERIFIED_SESSION_KEY, None)
        # 本人还在用着这个会话，改密后保持登录；其他设备的会话会失效。
        update_session_auth_hash(request, request.user)
        messages.success(request, '密码已重置。其他设备上的登录需要重新登录。')
        return redirect(reverse('profile') + '?tab=security')
    if request.method == 'POST':
        messages.error(request, '新密码不符合要求，请按提示修改。')
    return render(request, 'core/password_code_new_password.html', {
        'form': form,
        'masked_email': _mask_email(request.user.email),
    })


@login_required
@never_cache
def profile(request):
    """个人中心：账号资料、角色权限清单，以及修改密码。

    资料、改密和邮箱验证用隐藏的 action 字段区分；改密成功后刷新会话摘要，
    当前登录状态保持有效。
    """
    from .email_binding import process as bind_email
    from .avatars import AvatarForm, save_avatar
    binding_context, binding_response = bind_email(request)
    if binding_response is not None:
        return binding_response
    setting_tab = request.GET.get('tab', 'account')
    if setting_tab != 'security': setting_tab = 'account'
    profile_form = ProfileForm(instance=request.user)
    password_form = PasswordChangeForm(request.user)
    avatar_form = AvatarForm()
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'password':
            setting_tab = 'security'
            password_form = PasswordChangeForm(request.user, request.POST)
            if password_form.is_valid():
                update_session_auth_hash(request, password_form.save())
                messages.success(request, '密码已更新。')
                return redirect(reverse('profile') + '?tab=security')
        elif action == 'profile':
            setting_tab = 'account'
            profile_form = ProfileForm(request.POST, instance=request.user)
            if profile_form.is_valid():
                profile_form.save()
                messages.success(request, '个人资料已更新。')
                return redirect('profile')
        elif action in ('email_send', 'email_verify', 'email_cancel'):
            setting_tab = 'account'
        elif action == 'avatar':
            avatar_form = AvatarForm(request.POST, request.FILES)
            if avatar_form.is_valid():
                save_avatar(request.user, avatar_form.cleaned_data['avatar'])
                messages.success(request, '头像已更新。')
                return redirect('profile')
        elif action == 'avatar_remove':
            save_avatar(request.user)
            messages.success(request, '已恢复默认头像。')
            return redirect('profile')
        else:
            raise PermissionDenied
    return render(request, 'core/profile.html', {
        **binding_context,
        'setting_tab': setting_tab,
        'profile_form': profile_form,
        'password_form': password_form,
        'avatar_form': avatar_form,
        'is_admin': perms.is_admin(request),
        'account_role_label': perms.role_label(perms.account_role(request.user)),
        'role_label': perms.role_label(request.role),
        'owned_projects': Project.objects.filter(owner=request.user, archived_at__isnull=True)
                                        .order_by('name'),
        'joined_projects': request.user.projects.filter(archived_at__isnull=True)
                                                .exclude(owner=request.user).order_by('name'),
        'open_tasks': Task.objects.filter(Q(assignee=request.user) | Q(members=request.user), archived_at__isnull=True, project__archived_at__isnull=True, parent__archived_at__isnull=True).distinct()
                                 .exclude(status=Task.COMPLETED).count(),
    })


@login_required
def change_password(request):
    """修改密码已并入个人中心，旧链接直接跳到那一节。"""
    return redirect(reverse('profile') + '?tab=security')


# --------------------------------------------------------------------------
# 聊天室（历史房间；日常沟通在 core/messages.py 的消息中心）
# --------------------------------------------------------------------------

def _render_chat(request, room, room_url, messages_url):
    """聊天室页面：GET 显示最近消息，POST 直接发一条（不开 JS 也能用）。"""
    perms.require_chat_room(request, room)
    if request.method == 'GET' and perms.is_team_member(request):
        return redirect(reverse('messages_hub') + ('?room=public' if room == ChatMessage.PUBLIC else ''))
    if request.method == 'POST':
        form = ChatMessageForm(request.POST)
        if form.is_valid():
            message = form.save(commit=False)
            message.room = room
            message.author = request.user
            message.save()
        else:
            messages.error(request, '消息不能为空，且不超过 2000 字。')
        return redirect(room_url)
    chat_log = list(visible_messages(request.user, ChatMessage.objects.filter(room=room, withdrawn_at__isnull=True))
                    .select_related('author__member_profile').order_by('-created_at', '-pk')[:200])
    chat_log.reverse()  # 按时间正序显示，最新的在底部。
    return render(request, 'core/chat.html', {
        'room': room,
        'room_label': dict(ChatMessage.ROOMS)[room],
        'room_url': room_url,
        'messages_url': messages_url,
        'rooms': perms.visible_chat_rooms(request),
        'chat_log': chat_log,
        'form': ChatMessageForm(),
        'total': ChatMessage.objects.filter(room=room).count(),
    })


@login_required
def chat(request):
    """聊天室入口：按当前身份落到能进的房间。"""
    rooms = perms.visible_chat_rooms(request)
    if not rooms:
        raise PermissionDenied('没有可以进入的聊天室。')
    room = rooms[0][0]
    return redirect(_CHAT_ROOM_URLS[room])


@login_required
def chat_public(request):
    return _render_chat(request, ChatMessage.PUBLIC, 'chat_public', 'chat_public_messages')


@login_required
def chat_developers(request):
    return _render_chat(request, ChatMessage.DEVELOPERS, 'chat_developers', 'chat_developers_messages')


@login_required
def chat_public_messages(request):
    return _chat_messages(request, ChatMessage.PUBLIC)


@login_required
def chat_developers_messages(request):
    return _chat_messages(request, ChatMessage.DEVELOPERS)


def _chat_messages(request, room):
    """轮询接口：只回传比 after 更新的消息，避免整页重刷。"""
    perms.require_chat_room(request, room)
    try:
        after = int(request.GET.get('after') or 0)
    except (TypeError, ValueError):
        after = 0
    rows = (visible_messages(request.user, ChatMessage.objects.filter(room=room, pk__gt=after, withdrawn_at__isnull=True))
            .select_related('author__member_profile').order_by('pk')[:200])
    return JsonResponse({
        'messages': [{
            'id': item.pk,
            'author': item.author.username,
            'initial': item.author.username[:1].upper(),
            'avatar_url': avatar_url(item.author),
            'body': '消息已撤回' if item.withdrawn_at else item.body,
            'at': item.spoken_at,
            'mine': item.author_id == request.user.pk,
        } for item in rows],
        'total': ChatMessage.objects.filter(room=room).count(),
    })


_CHAT_ROOM_URLS = {ChatMessage.PUBLIC: 'chat_public', ChatMessage.DEVELOPERS: 'chat_developers'}


# --------------------------------------------------------------------------
# 首页与任务总览
# --------------------------------------------------------------------------

@login_required
def dashboard(request):
    projects = Project.objects.filter(archived_at__isnull=True).select_related('owner')
    if request.GET.get('scope')=='mine':projects=projects.filter(Q(owner=request.user)|Q(members=request.user)).distinct()
    projects=page(request,projects)
    rows = Task.objects.filter(archived_at__isnull=True, project__archived_at__isnull=True, parent__archived_at__isnull=True).values_list('project_id', 'id', 'parent_id', 'progress')
    progress_map = summarise_progress(rows)
    open_counts = dict(Task.objects.filter(archived_at__isnull=True, project__archived_at__isnull=True, parent__archived_at__isnull=True).exclude(status=Task.COMPLETED)
                       .values_list('project_id').annotate(total=Count('id')))
    project_rows = [{
        'project': project,
        'progress': progress_map.get(project.pk, 0),
        'open_tasks': open_counts.get(project.pk, 0),
        'is_participant': project.is_participant(request.user),
    } for project in projects]
    mine = request.GET.get('scope') == 'mine'
    if mine:
        project_rows = [row for row in project_rows if row['is_participant']]

    my_tasks = Task.objects.filter(Q(assignee=request.user) | Q(members=request.user), archived_at__isnull=True, project__archived_at__isnull=True, parent__archived_at__isnull=True).distinct() \
        .exclude(status=Task.COMPLETED).select_related('project', 'parent').order_by('due_date', 'pk')
    latest_submissions = perms.visible_submissions(
        request, Submission.objects.select_related('author', 'task', 'project')
    ).order_by('-created_at', '-pk')[:6]
    latest_comments = Comment.objects.filter(task__archived_at__isnull=True, task__parent__archived_at__isnull=True, task__project__archived_at__isnull=True, project__archived_at__isnull=True).select_related('author', 'task', 'project', 'submission') \
        .order_by('-created_at', '-pk')[:6]
    return render(request, 'core/dashboard.html', {
        'project_rows': project_rows, 'projects_page':projects,
        'mine': mine,
        'my_tasks': my_tasks,
        'latest_submissions': latest_submissions,
        'latest_comments': latest_comments,
    })


@login_required
def task_list(request):
    """全部任务进度：所有开发者都可以查看。"""
    tasks = Task.objects.filter(archived_at__isnull=True, project__archived_at__isnull=True, parent__archived_at__isnull=True).select_related('project', 'parent', 'assignee', 'competition')
    status = request.GET.get('status', '')
    if status in dict(Task.STATUS):
        tasks = tasks.filter(status=status)
    mine = request.GET.get('mine') == '1'
    if mine:
        tasks = tasks.filter(Q(assignee=request.user) | Q(members=request.user)).distinct()
    category = request.GET.get('category', '')
    if category in dict(Task.CATEGORIES):
        tasks = tasks.filter(category=category)
    query = request.GET.get('q', '').strip()[:100]
    if query:
        tasks = tasks.filter(Q(title__icontains=query) | Q(project__name__icontains=query) | Q(competition__name__icontains=query))
    return render(request, 'core/task_list.html', {
        'tasks': page(request, tasks), 'status': status, 'mine': mine,
        'category': category, 'categories': Task.CATEGORIES, 'query': query,
    })


# --------------------------------------------------------------------------
# 项目
# --------------------------------------------------------------------------

@login_required
def project_detail(request, pk):
    project = _visible_project(request, pk)
    tasks = list(project.tasks.filter(archived_at__isnull=True, parent__archived_at__isnull=True)
                 .select_related('assignee', 'created_by', 'competition').order_by('due_date', 'created_at', 'pk'))
    mothers = [task for task in tasks if task.parent_id is None]
    for mother in mothers:
        mother.child_list = [task for task in tasks if task.parent_id == mother.pk]
    visible = list(perms.visible_submissions(
        request,
        Submission.objects.filter(Q(project=project) | Q(task__project=project))
        .select_related('author', 'task', 'project', 'reviewed_by', 'final_by')
    )[:120])
    project_tab = request.GET.get('tab', 'overview')
    if project_tab not in ('overview', 'tasks', 'results'): project_tab = 'overview'
    result_filter = request.GET.get('filter', 'all')
    if result_filter not in ('all', 'pending', 'final'): result_filter = 'all'
    if result_filter == 'pending' and not perms.can_review(request, project): result_filter = 'all'
    results = [item for item in visible if (result_filter == 'all' or
               result_filter == 'pending' and item.status == Submission.PENDING or
               result_filter == 'final' and item.is_final)]
    return render(request, 'core/project_detail.html', {
        'project': project,
        'mothers': mothers,
        'task_total': len(tasks),
        'members': project.members.order_by('username'),
        'can_work': perms.is_admin(request) or project.is_participant(request.user),
        'submission_form': SubmissionForm(project=project),
        'project_tab': project_tab, 'result_filter': result_filter, 'results': results,
        'project_results': [item for item in visible if item.project_id],
        'task_results': [item for item in visible if item.task_id][:15],
        'pending': [item for item in visible if item.status == Submission.PENDING],
        'final_results': [item for item in visible if item.is_final],
        'comments': list(project.comments.select_related('author').prefetch_related('attachments')),
        'task_comments': list(Comment.objects.filter(task__project=project)
                              .select_related('author', 'task').order_by('-created_at', '-pk')[:8]),
        'can_manage': perms.can_manage_project(request, project),
        'can_review': perms.can_review(request, project),
        'is_admin': perms.is_admin(request),
        **project_cost(project),
    })


@login_required
def project_edit(request, pk=None):
    """管理员创建项目、确定目标、指定项目负责人及成员。"""
    perms.require_admin(request)
    project = get_object_or_404(Project, pk=pk, archived_at__isnull=True) if pk else None
    previous_owner = project.owner_id if project else None
    form = ProjectForm(request.POST or None, instance=project, user=request.user)
    if request.method == 'POST' and form.is_valid():
        item = form.save(commit=False)
        if project and item.public_state == 'public' and ('public_summary' in form.changed_data or 'name' in form.changed_data):
            item.public_state = 'pending'
        if project is None:
            item.created_by = request.user
        item.save()
        form.save_m2m()
        item.members.remove(item.owner)
        if previous_owner and previous_owner != item.owner_id:
            item.members.add(previous_owner)  # 原负责人保留为项目成员。
        messages.success(request, '项目已保存。')
        return redirect('project_detail', pk=item.pk)
    return render(request, 'core/project_form.html', {'form': form, 'project': project})


@login_required
@require_POST
def project_close(request, pk):
    """项目结项或重新打开：属最终成果审批范围，仅管理员。"""
    perms.require_admin(request)
    project = _visible_project(request, pk)
    if project.status == Project.CLOSED:
        project.status = Project.ACTIVE
        project.closed_at = None
        project.closed_by = None
        messages.success(request, '项目已重新打开。')
    else:
        project.status = Project.CLOSED
        project.closed_at = timezone.now()
        project.closed_by = request.user
        messages.success(request, '项目已结项。管理员可随时重新打开。')
    project.save(update_fields=['status', 'closed_at', 'closed_by', 'updated_at'])
    return redirect('project_detail', pk=project.pk)


@login_required
@require_POST
def project_archive(request, pk):
    perms.require_admin(request)
    project = _visible_project(request, pk)
    project.archived_at = timezone.now()
    project.save(update_fields=['archived_at', 'updated_at'])
    messages.success(request, '项目已删除，可在回收站恢复。')
    return redirect('dashboard')


# --------------------------------------------------------------------------
# 任务（母任务／子任务）
# --------------------------------------------------------------------------

@login_required
def task_detail(request, pk, submission_form=None, open_result=False):
    task = _visible_task(request, pk)
    project = task.project
    children = list(task.children.filter(archived_at__isnull=True).select_related('assignee', 'competition'))
    submissions = list(perms.visible_submissions(
        request, task.submissions.select_related('author', 'reviewed_by', 'final_by')
    ).prefetch_related('attachments', 'comments__author'))
    comments = list(task.comments.filter(submission__isnull=True).select_related('author').prefetch_related('attachments'))
    activity = [{'kind':'submission','item':item,'time':item.created_at} for item in submissions]
    activity += [{'kind':'comment','item':item,'time':item.created_at} for item in comments]
    activity.sort(key=lambda event: event['time'])
    return render(request, 'core/task_detail.html', {
        'task': task,
        'project': project,
        'children': children,
        'parent': task.parent,
        'submissions': submissions,
        'activity': activity,
        'pending': [item for item in submissions if item.status == Submission.PENDING],
        'final_results': [item for item in submissions if item.is_final],
        'comments': comments,
        'is_assignee': perms.can_work_task(request, task),
        'can_manage': perms.can_manage_project(request, project),
        'can_review': perms.can_review(request, project),
        'is_admin': perms.is_admin(request),
        'can_work': perms.can_work_task(request, task),
        'can_close': perms.can_manage_project(request, project) or (bool(task.parent_id) and perms.can_work_task(request, task)),
        'can_create_child': perms.can_manage_project(request, project) or project.is_participant(request.user),
        'submission_form': submission_form if submission_form is not None else SubmissionForm(project=project, task=task),
        'open_result': open_result,
        'inline_experiment_open': request.POST.get('create_experiment') == '1',
        'progress_form': ProgressForm(initial={'progress': min(task.progress, 99)}),
        'review_form': ReviewForm(),
    })


@login_required
def task_edit(request, pk=None):
    """发布或修改任务：管理员，或该项目负责人（权限限定在自己负责的项目内）。"""
    task = _visible_task(request, pk) if pk else None
    if task:
        project, parent = task.project, task.parent
    else:
        project = _visible_project(request, request.GET.get('project') or request.POST.get('project'))
        parent = None
        parent_id = request.GET.get('parent') or request.POST.get('parent')
        if parent_id:
            parent = get_object_or_404(Task, pk=parent_id, project=project, parent__isnull=True,
                                       archived_at__isnull=True)
    if not (perms.can_manage_project(request, project) or (not task and parent and project.is_participant(request.user))):
        raise PermissionDenied
    instance = task or Task(project=project, parent=parent, created_by=request.user)
    initial = {'assignee': request.user.pk} if not task and project.is_participant(request.user) else {}
    if parent and not task:
        initial.update(category=parent.category, competition=parent.competition_id)
    form = TaskForm(request.POST or None, instance=instance, project=project, parent=parent, initial=initial, user=request.user)
    if request.method == 'POST' and form.is_valid():
        item = form.save()
        messages.success(request, '任务已保存。')
        return redirect('task_detail', pk=item.pk)
    return render(request, 'core/task_form.html', {
        'form': form, 'task': task, 'project': project, 'parent': parent,
    })


@login_required
@require_POST
def task_progress(request, pk):
    task = _visible_task(request, pk)
    perms.require_progress_worker(request, task)
    if task.status != Task.OPEN:
        messages.error(request, '任务已提交或已结项，不能直接改进度。')
        return _back_to(request, 'task_detail', pk=pk)
    form = ProgressForm(request.POST)
    if form.is_valid():
        task.progress = form.cleaned_data['progress']
        task.save(update_fields=['progress', 'updated_at'])
        messages.success(request, '进度已更新。')
    else:
        messages.error(request, '进度应为 0 到 99。')
    return _back_to(request, 'task_detail', pk=pk)


@login_required
@require_POST
def task_submit(request, pk):
    """发布成果：每个开发者都可以对任务发布成果，正文纯文本即可，附件可选。

    任务已结项时不再接收新成果（可由管理员或项目负责人重新打开）。
    """
    task = _visible_task(request, pk)
    if not perms.can_work_task(request, task):
        raise PermissionDenied
    inline = request.POST.get('create_experiment') == '1'
    form = SubmissionForm(request.POST, request.FILES, instance=Submission(task=task), project=task.project)
    submission_valid = form.is_valid()
    if not submission_valid:
        messages.error(request, '请修正下方填写内容后重新提交。')
        return task_detail(request, pk, submission_form=form, open_result=True)
    with transaction.atomic():
        task = Task.objects.select_for_update().get(pk=task.pk)
        if task.status == Task.COMPLETED:
            messages.error(request, '任务已结项，如需补充成果请先重新打开任务。')
            return _back_to(request, 'task_detail', pk=pk)
        submission = form.save(commit=False)
        submission.task = task
        submission.project = None
        submission.author = request.user
        submission.save()
        form.save_m2m()
        files = attach_files('submission', submission, form.cleaned_data['attachments'], request.user)
        if inline:
            import uuid
            experiment = Experiment.objects.create(number='EXP-' + uuid.uuid4().hex[:12].upper(),
                title=task.title, content=submission.summary, github_url=submission.source_url,
                project=task.project, origin_task=task, created_by=request.user)
            submission.experiments.add(experiment)
            for file in files:
                Attachment.objects.create(experiment=experiment, file=file.file.name,
                    original_name=file.original_name, uploaded_by=request.user)
        if request.POST.get('submission_action') == 'finish':
            if task.parent_id:
                submission.status = Submission.ACCEPTED
                submission.reviewed_by = request.user
                submission.reviewed_at = timezone.now()
                submission.review_note = '子任务自主结项'
                submission.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'review_note'])
                task.status, task.progress = Task.COMPLETED, 100
                task.closed_at, task.closed_by = timezone.now(), request.user
                task.save(update_fields=['status', 'progress', 'closed_at', 'closed_by', 'updated_at'])
            else:
                task.status = Task.SUBMITTED
                task.save(update_fields=['status', 'updated_at'])
    messages.success(request, '成果已提交，子任务已结项。' if task.status == Task.COMPLETED else '成果已提交。')
    return _back_to(request, 'task_detail', pk=pk)


@login_required
@require_POST
def task_comment(request, pk):
    """任务留言：每个开发者都可以留言，记录目标、思路、问题和结论。"""
    task = _visible_task(request, pk)
    form = CommentForm(request.POST, request.FILES, instance=Comment(task=task))
    if form.is_valid():
        comment = form.save(commit=False)
        comment.author = request.user
        comment.save()
        attach_files('comment', comment, form.cleaned_data['attachments'], request.user)
        messages.success(request, '留言已发布。')
    else:
        messages.error(request, '留言内容不能为空。')
    return _back_to(request, 'task_detail', pk=pk)


@login_required
@require_POST
def task_close(request, pk):
    """项目内结项子任务：管理员或项目负责人可直接结项，也可重新打开。"""
    task = _visible_task(request, pk)
    if not (perms.can_manage_project(request, task.project) or (task.parent_id and perms.can_work_task(request, task))):
        raise PermissionDenied
    note = (request.POST.get('note') or '').strip()
    if task.status == Task.COMPLETED:
        task.status = Task.OPEN
        task.closed_at = None
        task.closed_by = None
        messages.success(request, '任务已重新打开。')
    else:
        task.status = Task.COMPLETED
        task.progress = 100
        task.closed_at = timezone.now()
        task.closed_by = request.user
        messages.success(request, '任务已结项。')
    task.save(update_fields=['status', 'progress', 'closed_at', 'closed_by', 'updated_at'])
    if note:
        Comment.objects.create(task=task, kind=Comment.CONCLUSION, body=note, author=request.user)
    return redirect('task_detail', pk=task.pk)


@login_required
@require_POST
def task_archive(request, pk):
    task = _visible_task(request, pk)
    perms.require_project_manager(request, task.project)
    task.archived_at = timezone.now()
    task.save(update_fields=['archived_at', 'updated_at'])
    messages.success(request, '任务已删除，可在回收站恢复。')
    return redirect('project_detail', pk=task.project_id)


@login_required
@require_POST
def project_comment(request, pk):
    """项目留言：每个开发者都可以在项目页留言。"""
    project = _visible_project(request, pk)
    form = CommentForm(request.POST, request.FILES, instance=Comment(project=project))
    if form.is_valid():
        comment = form.save(commit=False)
        comment.author = request.user
        comment.save()
        attach_files('comment', comment, form.cleaned_data['attachments'], request.user)
        messages.success(request, '留言已发布。')
    else:
        messages.error(request, '留言内容不能为空。')
    return _back_to(request, 'project_detail', pk=pk)


@login_required
@require_POST
def project_submit(request, pk):
    """项目成果：不属于单个任务的产出（例如结题报告、数据集），每个开发者都可以发布。"""
    project = _visible_project(request, pk)
    if not (perms.is_admin(request) or project.is_participant(request.user)):
        raise PermissionDenied
    form = SubmissionForm(request.POST, request.FILES, instance=Submission(project=project), project=project)
    if not form.is_valid():
        messages.error(request, '发布失败：请填写成果内容；附件需为允许的类型且不超过大小限制。')
        return _back_to(request, 'project_detail', pk=pk)
    submission = form.save(commit=False)
    submission.project = project
    submission.task = None
    submission.author = request.user
    submission.save()
    form.save_m2m()
    attach_files('submission', submission, form.cleaned_data['attachments'], request.user)
    messages.success(request, '成果已发布，等待审核。')
    return _back_to(request, 'project_detail', pk=pk)


# --------------------------------------------------------------------------
# 成果与附件
# --------------------------------------------------------------------------

@login_required
@require_POST
def submission_review(request, pk):
    """审核成果：管理员审核最终成果，项目负责人在项目内审核。"""
    submission = get_object_or_404(Submission.objects.select_related('task', 'project'), pk=pk)
    project = submission.owner_project
    perms.require_reviewer(request, project)
    form = ReviewForm(request.POST)
    if not form.is_valid():
        messages.error(request, '请检查审核决定；退回时必须填写原因。')
        return _submission_back(request, submission)
    with transaction.atomic():
        submission = Submission.objects.select_for_update().select_related('task', 'project').get(pk=pk)
        if submission.status != Submission.PENDING:
            messages.error(request, '该成果已经审核过了。')
            return _submission_back(request, submission)
        approved = form.cleaned_data['decision'] == 'accept'
        submission.status = Submission.ACCEPTED if approved else Submission.REJECTED
        submission.review_note = form.cleaned_data['note']
        submission.reviewed_by = request.user
        submission.reviewed_at = timezone.now()
        submission.save(update_fields=['status', 'review_note', 'reviewed_by', 'reviewed_at'])
        if submission.task_id:
            task = Task.objects.select_for_update().get(pk=submission.task_id)
            _sync_task_status(task, request.user)
    messages.success(request, '审核结果已保存。')
    return _submission_back(request, submission)


@login_required
@require_POST
def submission_final(request, pk):
    """选取有价值的成果作为最终成果：仅管理员，且不必等所有分支完成。"""
    perms.require_admin(request)
    submission = get_object_or_404(Submission.objects.select_related('task', 'project'), pk=pk)
    if request.POST.get('action') == 'unmark':
        submission.is_final = False
        submission.final_note = ''
        submission.final_by = None
        submission.final_at = None
        messages.success(request, '已取消最终成果标记。')
    else:
        form = FinalForm(request.POST)
        submission.is_final = True
        submission.final_note = (form.cleaned_data['note'] if form.is_valid() else '') or ''
        submission.final_by = request.user
        submission.final_at = timezone.now()
        messages.success(request, '已选为最终成果。')
    submission.save(update_fields=['is_final', 'final_note', 'final_by', 'final_at'])
    return _submission_back(request, submission)


@login_required
@require_POST
def submission_comment(request, pk):
    """针对具体成果留言提问，便于追溯上下文。"""
    submission = get_object_or_404(Submission.objects.select_related('task', 'project'), pk=pk)
    form = CommentForm(request.POST, request.FILES, instance=Comment(submission=submission))
    if form.is_valid():
        comment = form.save(commit=False)
        comment.author = request.user
        comment.save()
        attach_files('comment', comment, form.cleaned_data['attachments'], request.user)
        messages.success(request, '留言已发布。')
    else:
        messages.error(request, '留言内容不能为空。')
    return _submission_back(request, submission)


@login_required
def attachment_download(request, pk):
    """私有附件下载：逐个判断权限，绝不提供公开文件 URL。"""
    attachment = get_object_or_404(Attachment.objects.select_related(
        'submission__task__project', 'comment', 'claim', 'entry', 'experiment', 'chat_message'), pk=pk)
    if not perms.can_download_attachment(request, attachment):
        raise PermissionDenied
    try:
        return FileResponse(attachment.file.open('rb'), as_attachment=True,
                            filename=attachment.original_name or 'attachment')
    except FileNotFoundError:
        raise Http404('文件不存在')


# --------------------------------------------------------------------------
# 人员：邀请码与成员任免
# --------------------------------------------------------------------------

@login_required
def invites(request):
    perms.require_admin(request)
    fresh_code = None
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'create':
            invite, fresh_code = Invite.issue(request.user)
        elif action == 'revoke':
            invite = get_object_or_404(Invite, pk=request.POST.get('id'), used_at__isnull=True,
                                       revoked_at__isnull=True)
            invite.revoked_at = timezone.now()
            invite.save(update_fields=['revoked_at'])
            messages.success(request, '邀请码已撤销。')
            return redirect('invites')
        else:
            raise PermissionDenied
    return render(request, 'core/invites.html', {
        'invites': page(request,Invite.objects.select_related('used_by')), 'fresh_code': fresh_code,
    })


@login_required
@never_cache
def members(request):
    from .member_management import directory, lock_target, last_admin
    from .models import TeamMembership
    from .tenancy import required_team_id
    if request.method != 'POST': return directory(request)
    perms.require_admin(request)
    raw=request.POST.get('id','')
    if not raw.isascii() or not raw.isdigit() or len(raw)>18:raise Http404
    action=request.POST.get('action')
    if action not in ('deactivate','activate','promote','demote','make_developer'):raise PermissionDenied
    with transaction.atomic():
        target=lock_target(request,int(raw))
        member=TeamMembership.objects.get(team_id=required_team_id(),user=target,deleted_at__isnull=True)
        if member.role=='owner':
            messages.error(request,'团队所有者须先交接所有权。')
        elif action in ('deactivate','demote') and last_admin(target):
            messages.error(request,'至少保留一名在用团队管理员。')
        else:
            if action=='deactivate':member.active=False
            elif action=='activate':member.active=True
            elif action=='promote':member.active=True;member.role='admin'
            else:member.role='member'
            member.save(update_fields=['active','role'])
            messages.success(request,f'{target.username} 在本团队的权限已更新。')
    return redirect('members')


# --------------------------------------------------------------------------
# 财务：报销申请与团队账本合并在一页
# --------------------------------------------------------------------------

@login_required
def finance_list(request, claim_form=None):
    """财务页：上半部分是报销申请，下半部分是团队账本。

    账本与报销申请对全体团队成员可见（报销包含他人待审的申请，与账本口径一致）；
    普通用户由中间件挡在页面之外，这里再显式判定一次，避免只靠中间件保护。
    """
    if not perms.is_team_member(request):
        raise PermissionDenied('财务服务仅供团队成员使用。')
    is_admin = perms.is_admin(request)
    # 余额与合计必须按整本账本聚合，且只算未作废账目：列表只显示最近 200 条，
    # 先切片再求和会在账目超过 200 条时静默算错；作废记录对管理员仍显示在列表里，但不计入余额。
    totals = FinanceEntry.objects.filter(voided_at__isnull=True, archived_at__isnull=True).aggregate(
        income=Sum('amount', filter=~Q(kind__in=OUTFLOW_KINDS), default=Decimal('0')),
        outflow=Sum('amount', filter=Q(kind__in=OUTFLOW_KINDS), default=Decimal('0')),
    )
    income = money(totals['income'])
    outflow = money(totals['outflow'])
    shown = FinanceEntry.objects.filter(archived_at__isnull=True).select_related('created_by', 'voided_by').prefetch_related('attachments')
    if not is_admin:
        shown = shown.filter(voided_at__isnull=True)  # 作废记录只对管理员可见。
    entries = page(request, shown)
    claims = ExpenseClaim.objects.filter(archived_at__isnull=True).select_related('applicant', 'reviewed_by', 'entry', 'project') \
                                 .prefetch_related('attachments')
    pending = ExpenseClaim.objects.filter(status=ExpenseClaim.PENDING, archived_at__isnull=True)
    return render(request, 'core/finance_list.html', {
        'entries': entries,
        'income': income,
        'outflow': outflow,
        'balance': income - outflow,
        'is_admin': is_admin,
        'claims': page(request, claims, key='claims_page'),
        'finance_tab': 'claims' if claim_form is not None or request.GET.get('tab') == 'claims' else 'ledger',
        'claim_form': claim_form if claim_form is not None else ClaimForm(user=request.user),
        'pending_claims': pending.count(),
    })


@login_required
def finance_edit(request, pk=None):
    perms.require_admin(request)
    entry = get_object_or_404(FinanceEntry, pk=pk, voided_at__isnull=True, archived_at__isnull=True) if pk else None
    form = FinanceForm(request.POST or None, request.FILES or None, instance=entry)
    if request.method == 'POST' and form.is_valid():
        item = form.save(commit=False)
        if entry is None:
            item.created_by = request.user
        item.save()
        attach_files('entry', item, form.cleaned_data['attachments'], request.user)
        messages.success(request, '财务记录已保存。')
        return redirect(reverse('finance_list') + '?tab=ledger')
    return render(request, 'core/finance_form.html', {'form': form, 'entry': entry})


@login_required
@require_POST
def finance_void(request, pk):
    perms.require_admin(request)
    entry = get_object_or_404(FinanceEntry, pk=pk, voided_at__isnull=True, archived_at__isnull=True)
    entry.voided_at = timezone.now()
    entry.voided_by = request.user
    entry.save(update_fields=['voided_at', 'voided_by', 'updated_at'])
    messages.success(request, '记录已作废，仍保留在账本中备查。')
    return redirect(reverse('finance_list') + '?tab=ledger')


@login_required
@require_POST
def finance_archive(request, pk):
    perms.require_admin(request)
    with transaction.atomic():
        entry = get_object_or_404(FinanceEntry.objects.select_for_update(), pk=pk, archived_at__isnull=True)
        entry.archived_at = timezone.now()
        entry.save(update_fields=['archived_at', 'updated_at'])
        ExpenseClaim.objects.filter(entry=entry).update(archived_at=entry.archived_at)
    messages.success(request, '财务记录已移入回收站，不再计入统计；可以恢复或彻底删除。')
    return redirect(reverse('finance_list') + '?tab=ledger')


@login_required
@require_POST
def claim_archive(request, pk):
    with transaction.atomic():
        claim = get_object_or_404(ExpenseClaim.objects.select_for_update(), pk=pk, archived_at__isnull=True)
        if not perms.is_admin(request) and not (perms.is_team_member(request) and claim.applicant_id == request.user.pk and claim.status == ExpenseClaim.PENDING):
            raise PermissionDenied
        claim.archived_at = timezone.now()
        claim.save(update_fields=['archived_at'])
        if claim.entry_id:
            FinanceEntry.objects.filter(pk=claim.entry_id).update(archived_at=claim.archived_at, updated_at=claim.archived_at)
    messages.success(request, '报销申请已移入回收站；关联账目也已移出统计。')
    return redirect(reverse('finance_list') + '?tab=claims')


@login_required
def claim_list(request):
    """报销申请已并入财务页，旧链接直接跳到报销区。"""
    return redirect(reverse('finance_list') + '?tab=claims')


@login_required
def claim_new(request):
    """成员提交报销申请及发票等凭证；表单就在财务页的报销区里。"""
    if request.method != 'POST':
        return redirect(reverse('finance_list') + '?tab=claims#claim-new')
    form = ClaimForm(request.POST, request.FILES, user=request.user)
    if form.is_valid():
        claim = form.save(commit=False)
        claim.applicant = request.user
        claim.save()
        attach_files('claim', claim, form.cleaned_data['attachments'], request.user)
        messages.success(request, '报销申请已提交，等待管理员审核。')
    else:
        messages.error(request, '报销申请未提交：请填写金额和事由；凭证需为允许的类型且不超过大小限制。')
        return finance_list(request, claim_form=form)
    return redirect(reverse('finance_list') + '?tab=claims')


@login_required
@require_POST
def claim_review(request, pk):
    """管理员决定报销是否通过；通过时自动入账，凭证同时挂到账本记录上。"""
    perms.require_admin(request)
    decision = request.POST.get('decision')
    if decision not in ('approve', 'reject'):
        raise PermissionDenied
    note = (request.POST.get('note') or '').strip()
    if decision == 'reject' and not note:
        messages.error(request, '驳回时请填写原因。')
        return redirect(reverse('finance_list') + '?tab=claims')
    with transaction.atomic():
        claim = get_object_or_404(ExpenseClaim.objects.select_for_update(), pk=pk, archived_at__isnull=True)
        if claim.status != ExpenseClaim.PENDING:
            messages.error(request, '该申请已经处理过了。')
            return redirect(reverse('finance_list') + '?tab=claims')
        if decision == 'approve':
            entry = FinanceEntry.objects.create(
                kind='reimburse', amount=claim.amount, occurred_on=claim.occurred_on,
                project=claim.project,  # 报销归属的项目带入账本，供项目成本汇总。
                memo=f'报销：{claim.applicant.username} · {claim.memo}', created_by=request.user)
            for attachment in claim.attachments.all():
                Attachment.objects.create(entry=entry, file=attachment.file.name,
                                          original_name=attachment.original_name,
                                          uploaded_by=attachment.uploaded_by)
            claim.entry = entry
            claim.status = ExpenseClaim.APPROVED
        else:
            claim.status = ExpenseClaim.REJECTED
        claim.review_note = note
        claim.reviewed_by = request.user
        claim.reviewed_at = timezone.now()
        claim.save(update_fields=['entry', 'status', 'review_note', 'reviewed_by', 'reviewed_at'])
    messages.success(request, '报销申请已通过并入账。' if decision == 'approve' else '报销申请已驳回。')
    return redirect(reverse('finance_list') + '?tab=claims')


@login_required
def team_manage(request):
    perms.require_admin(request)
    return render(request, 'core/team_manage.html')
