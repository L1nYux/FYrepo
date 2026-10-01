"""工作台视图。

页面分工：
- 项目展示：对外展示项目用，内容还在开发中，先给占位说明。
- 关于：团队介绍，目前只列出管理员与开发者。
- 聊天室：开发者聊天室（管理员＋开发者）与公共聊天室（所有登录用户），轮询拉新消息。
- 工作台首页：项目总览、我的任务、最新进展。
- 项目页：目标、成员、任务树（母任务／子任务）、最新成果与留言。
- 任务页：说明、进度、子任务、成果与审核、留言。
- 个人中心：账号名、姓名、邮箱、角色与权限清单，并在这里修改密码。
- 财务：账本与报销合并为一页（报销区在前，账本在后），仅管理员可记账、作废与审批。
- 人员：邀请码与成员任免（仅管理员）。
- 深色模式：由浏览器偏好与本地设置决定，不需要登录状态（见 static/core/site.js）。

角色由 core/permissions.py 统一判定，生效角色来自登录时选择的身份（见 core/middleware.py）：

- 管理员登录：完整界面。
- 开发者登录：没有后台入口、没有全局审核、看不到邀请码。
- 普通用户登录：只能看项目展示、公共聊天室与关于页面，其余页面由中间件跳回项目展示。

所有页面都要求登录，访客看不到任何内容。
"""

import hashlib
import json

from django.contrib import messages
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.models import User
from django.contrib.auth.views import LoginView, LogoutView
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import permissions as perms
from .forms import (ChatMessageForm, ClaimForm, CommentForm, FinalForm, FinanceForm,
                    NormalUserRegisterForm, ProfileForm, ProgressForm, ProjectForm, RegisterForm,
                    ReviewForm, RoleLoginForm, SubmissionForm, TaskForm, ExperimentForm)
from .models import (Attachment, ChatMessage, Comment, ExpenseClaim, FinanceEntry, Invite,
                     MemberProfile, Project, Submission, Task, ExperimentTemplate, attach_files, summarise_progress)


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
    """操作后回到来源页面（只接受同站相对路径），否则回退到指定页面。"""
    target = (request.POST.get('next') or '').strip()
    if target.startswith('/') and not target.startswith('//'):
        return redirect(target)
    return redirect(fallback, **kwargs)


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
    """登录：先在登录页选身份，再校验账号有没有这个身份。

    选择高于账号层级的身份（例如开发者选管理员登录）不写入会话，直接在表单上提示权限不足。
    选择低于账号层级的身份属于降级查看，按所选身份展示界面。
    """

    template_name = 'core/login.html'
    form_class = RoleLoginForm

    def get_success_url(self):
        # form_valid() 里已经校验过身份，这里直接用；兜底再读一次会话。
        role = getattr(self, 'role', None) or self.request.session.get(perms.SESSION_KEY)
        return reverse(perms.home_url_name(role))

    def form_valid(self, form):
        user = form.get_user()
        role = perms.account_role(user)
        if not perms.can_login_as(user, role):
            form.add_error('role', perms.role_error(user, role))
            return self.form_invalid(form)
        self.role = role  # 必须在 super() 之前，get_success_url() 会用到。
        response = super().form_valid(form)
        self.request.session[perms.SESSION_KEY] = role
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
                invite = Invite.objects.filter(code_hash=digest, used_at__isnull=True,
                                               revoked_at__isnull=True, expires_at__gt=now).first()
                if invite is None:
                    form.add_error('invite_code', '邀请码无效、已使用或已过期。')
                else:
                    user = form.save(commit=False)
                    user.is_staff = False
                    user.is_superuser = False
                    user.save()
                    MemberProfile.objects.update_or_create(user=user, defaults={'tier': MemberProfile.DEVELOPER})
                    changed = Invite.objects.filter(pk=invite.pk, used_at__isnull=True,
                                                    revoked_at__isnull=True, expires_at__gt=now).update(
                        used_by=user, used_at=now)
                    if changed != 1:
                        raise IntegrityError('邀请码已被使用')
                    login(request, user)
                    request.session[perms.SESSION_KEY] = perms.DEVELOPER
                    return redirect('dashboard')
        except IntegrityError:
            form.add_error('invite_code', '邀请码已被使用，请联系管理员。')
    return render(request, 'core/register.html', {'form': form, 'auth_view': 'register'})


def register_normal(request):
    """普通用户自助注册：不需要邀请码，注册后只能看到展示、公共聊天室和关于页面。"""
    if request.user.is_authenticated:
        return redirect(_role_home(role=request.role))
    form = NormalUserRegisterForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            user = form.save()
            MemberProfile.objects.update_or_create(user=user, defaults={'tier': MemberProfile.NORMAL})
            login(request, user)
            request.session[perms.SESSION_KEY] = perms.NORMAL
        messages.success(request, '普通用户账号已创建，当前以普通用户身份进入。')
        return redirect('showcase')
    return render(request, 'core/register_user.html', {'form': form})


@login_required
@require_POST
def switch_role(request):
    """在右上角菜单里切换身份视图，不必退出重新登录。"""
    role = request.POST.get('role')
    if not perms.can_login_as(request.user, role):
        messages.error(request, perms.role_error(request.user, role))
        return redirect(perms.home_url_name(request.role))
    request.session[perms.SESSION_KEY] = role
    messages.success(request, f'已切换为{perms.role_label(role)}视图。')
    return redirect(perms.home_url_name(role))



@login_required
def profile(request):
    """个人中心：账号资料、角色权限清单，以及修改密码。

    页面上有两个表单（资料、改密），用隐藏的 action 字段区分；改密成功后刷新会话摘要，
    当前登录状态保持有效。
    """
    setting_tab = request.GET.get('tab', 'account')
    if setting_tab not in ('account', 'security', 'appearance'): setting_tab = 'account'
    profile_form = ProfileForm(instance=request.user)
    password_form = PasswordChangeForm(request.user)
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
        else:
            raise PermissionDenied
    return render(request, 'core/profile.html', {
        'setting_tab': setting_tab,
        'profile_form': profile_form,
        'password_form': password_form,
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
# 项目展示 · 关于 · 聊天室
# --------------------------------------------------------------------------

@login_required
def showcase(request):
    """项目展示：内容还在开发中，先给出一句占位说明，具体项目稍后放上来。"""
    return render(request, 'core/showcase.html')


@login_required
def about(request):
    """关于：目前只展示管理员与开发者（普通用户不在名单里）。

    普通用户没有账号档案的按开发者处理，所以这里用反向排除来取名单，
    避免 LEFT JOIN 下 tier 为空的行被 exclude 掉。
    """
    normal_ids = set(MemberProfile.objects.filter(tier=MemberProfile.NORMAL)
                     .values_list('user_id', flat=True))
    accounts = User.objects.filter(is_active=True).order_by('-is_staff', 'username')
    return render(request, 'core/about.html', {
        'admins': [item for item in accounts if item.is_staff],
        'developers': [item for item in accounts if not item.is_staff and item.pk not in normal_ids],
        'normal_user_total': User.objects.filter(is_active=True, pk__in=normal_ids).count(),
    })


def _render_chat(request, room, room_url, messages_url):
    """聊天室页面：GET 显示最近消息，POST 直接发一条（不开 JS 也能用）。"""
    perms.require_chat_room(request, room)
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
    chat_log = list(ChatMessage.objects.filter(room=room)
                    .select_related('author').order_by('-created_at')[:200])
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
    rows = (ChatMessage.objects.filter(room=room, pk__gt=after)
            .select_related('author').order_by('pk')[:200])
    return JsonResponse({
        'messages': [{
            'id': item.pk,
            'author': item.author.username,
            'initial': item.author.username[:1].upper(),
            'body': item.body,
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
    projects = list(Project.objects.filter(archived_at__isnull=True).select_related('owner')[:50])
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
        .exclude(status=Task.COMPLETED).select_related('project', 'parent').order_by('due_date')
    latest_submissions = perms.visible_submissions(
        request, Submission.objects.select_related('author', 'task', 'project')
    ).order_by('-created_at')[:6]
    latest_comments = Comment.objects.filter(task__archived_at__isnull=True, task__parent__archived_at__isnull=True, task__project__archived_at__isnull=True, project__archived_at__isnull=True).select_related('author', 'task', 'project', 'submission') \
        .order_by('-created_at')[:6]
    return render(request, 'core/dashboard.html', {
        'project_rows': project_rows,
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
        'tasks': tasks[:300], 'status': status, 'mine': mine,
        'category': category, 'categories': Task.CATEGORIES, 'query': query,
    })


# --------------------------------------------------------------------------
# 项目
# --------------------------------------------------------------------------

@login_required
def project_detail(request, pk):
    project = _visible_project(request, pk)
    tasks = list(project.tasks.filter(archived_at__isnull=True, parent__archived_at__isnull=True)
                 .select_related('assignee', 'created_by', 'competition').order_by('due_date', 'created_at'))
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
                              .select_related('author', 'task').order_by('-created_at')[:8]),
        'can_manage': perms.can_manage_project(request, project),
        'can_review': perms.can_review(request, project),
        'is_admin': perms.is_admin(request),
    })


@login_required
def project_edit(request, pk=None):
    """管理员创建项目、确定目标、指定项目负责人及成员。"""
    perms.require_admin(request)
    project = get_object_or_404(Project, pk=pk, archived_at__isnull=True) if pk else None
    previous_owner = project.owner_id if project else None
    form = ProjectForm(request.POST or None, instance=project)
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
def task_detail(request, pk, submission_form=None, experiment_form=None, open_result=False):
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
        'experiment_form': experiment_form if experiment_form is not None else ExperimentForm(user=request.user, prefix='experiment', initial={'project': project.pk}),
        'experiment_presets': list(ExperimentTemplate.objects.values('id', 'name', 'parameters')),
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
    form = TaskForm(request.POST or None, instance=instance, project=project, parent=parent, initial=initial)
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
    form = SubmissionForm(request.POST, request.FILES, instance=Submission(task=task), project=task.project, inline_experiment=inline)
    experiment_form = ExperimentForm(request.POST, request.FILES, user=request.user, prefix='experiment', initial={'project': task.project_id}) if inline else None
    if experiment_form is not None:
        experiment_form.fields['project'].disabled = True
    submission_valid = form.is_valid()
    experiment_valid = experiment_form.is_valid() if inline else True
    if not submission_valid or not experiment_valid:
        messages.error(request, '请修正下方填写内容后重新提交。')
        return task_detail(request, pk, submission_form=form, experiment_form=experiment_form, open_result=True)
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
        if inline:
            experiment = experiment_form.save_record(origin_task=task)
            submission.experiments.add(experiment)
        attach_files('submission', submission, form.cleaned_data['attachments'], request.user)
        if form.cleaned_data['finish']:
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
    messages.success(request, '成果已发布，等待审核。')
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
        'invites': Invite.objects.select_related('used_by')[:100], 'fresh_code': fresh_code,
    })


@login_required
def members(request):
    """成员任免：启用／停用账号、设为管理员或降为开发者，也可以把普通用户升为开发者。

    「邀请开发者成为管理员」就是这里的 `promote`：管理员在名单上点一下即可，
    开发者下次登录选「管理员登录」就有完整界面。
    """
    perms.require_admin(request)
    if request.method == 'POST':
        action = request.POST.get('action')
        target = get_object_or_404(User, pk=request.POST.get('id'))
        if target.pk == request.user.pk:
            messages.error(request, '不能修改自己的账号状态，请让另一位管理员操作。')
            return redirect('members')
        active_admins = User.objects.filter(is_staff=True, is_active=True).count()
        if action == 'deactivate':
            if target.is_staff and active_admins <= 1:
                messages.error(request, '至少保留一名在用的管理员。')
            else:
                target.is_active = False
                target.save(update_fields=['is_active'])
                messages.success(request, f'{target.username} 已停用。')
        elif action == 'activate':
            target.is_active = True
            target.save(update_fields=['is_active'])
            messages.success(request, f'{target.username} 已启用。')
        elif action == 'promote':
            target.is_active = True
            target.is_staff = True
            target.save(update_fields=['is_active', 'is_staff'])
            MemberProfile.objects.update_or_create(
                user=target, defaults={'tier': MemberProfile.DEVELOPER})
            messages.success(request, f'{target.username} 已邀请成为管理员。')
        elif action == 'demote':
            if target.is_staff and active_admins <= 1:
                messages.error(request, '至少保留一名在用的管理员。')
            else:
                target.is_staff = False
                target.save(update_fields=['is_staff'])
                MemberProfile.objects.update_or_create(
                    user=target, defaults={'tier': MemberProfile.DEVELOPER})
                messages.success(request, f'{target.username} 已改为开发者。')
        elif action == 'make_developer':
            MemberProfile.objects.update_or_create(
                user=target, defaults={'tier': MemberProfile.DEVELOPER})
            messages.success(request, f'{target.username} 已升为开发者。')
        else:
            raise PermissionDenied
        return redirect('members')
    accounts = list(User.objects.annotate(owned=Count('owned_projects', distinct=True),
                                          assigned=Count('assigned_tasks', distinct=True))
                    .order_by('-is_staff', '-is_active', 'username'))
    tiers = dict(MemberProfile.objects.values_list('user_id', 'tier'))
    for account in accounts:
        if account.is_staff:
            account.tier = perms.ADMIN
        else:
            account.tier = tiers.get(account.pk, MemberProfile.DEVELOPER)
        account.role_label = perms.role_label(account.tier)
    return render(request, 'core/members.html', {'accounts': accounts})


# --------------------------------------------------------------------------
# 财务：报销申请与团队账本合并在一页
# --------------------------------------------------------------------------

@login_required
def finance_list(request):
    """财务页：上半部分是报销申请，下半部分是团队账本。

    账本对所有开发者可见，访客（未登录）看不到；报销申请成员只看自己的，管理员看全部。
    """
    is_admin = perms.is_admin(request)
    entries = FinanceEntry.objects.select_related('created_by', 'voided_by').prefetch_related('attachments')
    if not is_admin:
        entries = entries.filter(voided_at__isnull=True)
    entries = list(entries[:200])
    active = [entry for entry in entries if not entry.voided_at]
    income = sum(entry.amount for entry in active if entry.signed_amount > 0)
    outflow = sum(entry.amount for entry in active if entry.signed_amount < 0)
    claims = ExpenseClaim.objects.select_related('applicant', 'reviewed_by', 'entry') \
                                 .prefetch_related('attachments')
    pending = ExpenseClaim.objects.filter(status=ExpenseClaim.PENDING)
    if not is_admin:
        claims = claims.filter(applicant=request.user)
        pending = pending.filter(applicant=request.user)
    return render(request, 'core/finance_list.html', {
        'entries': entries,
        'income': income,
        'outflow': outflow,
        'balance': income - outflow,
        'is_admin': is_admin,
        'claims': claims[:200],
        'finance_tab': 'claims' if request.GET.get('tab') == 'claims' else 'ledger',
        'claim_form': ClaimForm(),
        'pending_claims': pending.count(),
    })


@login_required
def finance_edit(request, pk=None):
    perms.require_admin(request)
    entry = get_object_or_404(FinanceEntry, pk=pk, voided_at__isnull=True) if pk else None
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
    entry = get_object_or_404(FinanceEntry, pk=pk, voided_at__isnull=True)
    entry.voided_at = timezone.now()
    entry.voided_by = request.user
    entry.save(update_fields=['voided_at', 'voided_by', 'updated_at'])
    messages.success(request, '记录已作废，仍保留在账本中备查。')
    return redirect(reverse('finance_list') + '?tab=ledger')


@login_required
def claim_list(request):
    """报销申请已并入财务页，旧链接直接跳到报销区。"""
    return redirect(reverse('finance_list') + '?tab=claims')


@login_required
def claim_new(request):
    """成员提交报销申请及发票等凭证；表单就在财务页的报销区里。"""
    if request.method != 'POST':
        return redirect(reverse('finance_list') + '?tab=claims#claim-new')
    form = ClaimForm(request.POST, request.FILES)
    if form.is_valid():
        claim = form.save(commit=False)
        claim.applicant = request.user
        claim.save()
        attach_files('claim', claim, form.cleaned_data['attachments'], request.user)
        messages.success(request, '报销申请已提交，等待管理员审核。')
    else:
        messages.error(request, '报销申请未提交：请填写金额和事由；凭证需为允许的类型且不超过大小限制。')
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
        claim = get_object_or_404(ExpenseClaim.objects.select_for_update(), pk=pk)
        if claim.status != ExpenseClaim.PENDING:
            messages.error(request, '该申请已经处理过了。')
            return redirect(reverse('finance_list') + '?tab=claims')
        if decision == 'approve':
            entry = FinanceEntry.objects.create(
                kind='reimburse', amount=claim.amount, occurred_on=claim.occurred_on,
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
