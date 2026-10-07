"""Business permissions come from the selected workspace.

团队所有者和管理员管理本团队；成员参与业务；访客仅访问公开内容。
Software account administrators have separate capabilities and cannot access
other organizations' private business records through those capabilities.
"""

from django.core.exceptions import PermissionDenied
from django.db.models import Q

from .models import ChatMessage, MemberProfile, Submission

# 生效角色：普通用户 < 开发者 < 管理员。数值只用于比较，不参与运算。
NORMAL, DEVELOPER, ADMIN = 'normal', 'developer', 'admin'
RANK = {NORMAL: 0, DEVELOPER: 1, ADMIN: 2}
ROLE_LABELS = {NORMAL: '普通用户', DEVELOPER: '开发者', ADMIN: '管理员'}

# 登录页上的三个选项，按权限从高到低排列。
LOGIN_ROLES = [(ADMIN, '管理员登录'), (DEVELOPER, '开发者登录'), (NORMAL, '普通用户登录')]

# 会话里保存所选登录身份的键。
SESSION_KEY = 'workbench-login-role'

# 各身份登录后进入的首页。
HOME_URLS = {ADMIN: 'workspace_home', DEVELOPER: 'workspace_home', NORMAL: 'showcase'}


# --------------------------------------------------------------------------
# 角色解析
# --------------------------------------------------------------------------

def account_role(user):
    """Compatibility role for this workspace, never a global account identity."""
    if not user or not user.is_authenticated or not user.is_active:
        return None
    from .models import TeamMembership
    from .tenancy import team_id, personal_owner_id
    if personal_owner_id()==user.pk:
        return ADMIN
    member = TeamMembership.objects.filter(team_id=team_id(), user=user, active=True,
        deleted_at__isnull=True, team__active=True).first()
    return {'owner': ADMIN, 'admin': ADMIN, 'member': DEVELOPER, 'guest': NORMAL}.get(member.role if member else None, NORMAL)


def is_platform_admin(user):
    user = user_of(user)
    return bool(user and user.is_authenticated and user.is_active and user.is_superuser)


def user_of(viewer):
    """viewer 可能是 HttpRequest，也可能是 User；统一取出 User。"""
    return getattr(viewer, 'user', viewer)


def role_of(viewer):
    """当前生效的角色：请求优先用中间件写入的 request.role。"""
    chosen = getattr(viewer, 'role', None)
    if chosen in RANK:
        return chosen
    return account_role(user_of(viewer))


def rank_of(viewer):
    """生效角色的权限序号；访客为 -1，比任何已登录角色都低。"""
    return RANK.get(role_of(viewer), -1)


def role_label(role):
    return ROLE_LABELS.get(role, '访客')


def home_url_name(role):
    """该身份登录后应该落在哪个页面。"""
    return HOME_URLS.get(role, 'showcase')


def allowed_login_roles(user):
    """这个账号在登录页可选的身份：不高于账号自身的层级。"""
    account = account_role(user)
    if account is None:
        return []
    return [value for value, _ in LOGIN_ROLES if RANK[value] <= RANK[account]]


def can_login_as(user, role):
    """所选身份不能超过账号层级，否则属于越权，应当提示权限不足。"""
    account = account_role(user)
    return role in RANK and account is not None and RANK[role] <= RANK[account]


def role_error(user, role):
    """越权登录时的提示语，顺带告诉用户能选哪些身份。"""
    options = '、'.join(dict(LOGIN_ROLES)[value] for value in allowed_login_roles(user))
    hint = f'请改选{options}。' if options else ''
    return (f'权限不足：该账号是{role_label(account_role(user))}，'
            f'不能以「{role_label(role)}」身份登录。{hint}')


# --------------------------------------------------------------------------
# 管理员
# --------------------------------------------------------------------------

def is_admin(viewer):
    return role_of(viewer) == ADMIN


def require_admin(viewer):
    if not is_admin(viewer):
        raise PermissionDenied('需要管理员权限。')


# --------------------------------------------------------------------------
# 项目与任务的管理动作
# --------------------------------------------------------------------------

def is_project_owner(viewer, project):
    user = user_of(viewer)
    return bool(user.is_authenticated and project.owner_id == user.pk)


def is_team_member(viewer):
    """Business access: personal owner or active formal organization member."""
    return rank_of(viewer) >= RANK[DEVELOPER]


def can_manage_finance(viewer):
    from .team_permissions import allowed
    return is_admin(viewer) or allowed(viewer,'finance')

def require_finance(viewer):
    if not can_manage_finance(viewer):raise PermissionDenied('需要财务管理权限。')

def can_manage_project(viewer, project):
    """项目设置、任务拆分与结项：管理员或该项目负责人。"""
    if is_admin(viewer):
        return True
    from .team_permissions import allowed
    return is_team_member(viewer) and (is_project_owner(viewer, project) or allowed(viewer,'projects'))


def require_project_manager(viewer, project):
    if not can_manage_project(viewer, project):
        raise PermissionDenied('只有管理员或该项目负责人可以执行此操作。')


def can_update_progress(viewer, task):
    """更新进度：任务负责人本人；管理员可代为处理。"""
    if is_admin(viewer):
        return True
    return can_work_task(viewer, task)


def require_progress_worker(viewer, task):
    if not can_update_progress(viewer, task):
        raise PermissionDenied('只有任务负责人可以更新进度。')


# --------------------------------------------------------------------------
# 参与：留言与发布成果对全体开发者开放
# --------------------------------------------------------------------------

def can_comment(viewer, project=None):
    """留言：每个开发者都可以对任务、项目和成果留言。"""
    from .collaboration import participates
    return is_team_member(viewer) or project is not None and participates(user_of(viewer),project)


def can_publish_result(viewer, project=None):
    """发布成果：每个开发者都可以对任务和项目发布成果。"""
    from .collaboration import participates
    return is_team_member(viewer) or project is not None and participates(user_of(viewer),project)


# --------------------------------------------------------------------------
# 审核与可见性
# --------------------------------------------------------------------------

def can_review(viewer, project):
    """审核成果：管理员（最终成果审批）或项目负责人（项目内审核）。

    普通用户不参与审核；开发者登录本身没有全局审核入口，但自己负责的项目仍可审核
    （项目负责人是一项独立授权，与账号层级无关）。
    """
    if is_admin(viewer):
        return True
    if not is_team_member(viewer):
        return False
    return is_project_owner(viewer, project)


def require_reviewer(viewer, project):
    if not can_review(viewer, project):
        raise PermissionDenied('只有管理员或该项目负责人可以审核成果。')


def can_view_submission(viewer, submission):
    """成果可见性：作者、管理员和项目内成员可见全部；其他开发者只看已通过或已选用的成果。"""
    user = user_of(viewer)
    if is_admin(viewer) or submission.author_id == user.pk:
        return True
    from .collaboration import participates
    if participates(user,submission.owner_project):return True
    if not is_team_member(viewer):
        return False
    project = submission.owner_project
    if project.is_participant(user):
        return True
    return submission.status == Submission.ACCEPTED or submission.is_final


def visible_submissions(viewer, queryset):
    """按可见性规则过滤成果列表。"""
    queryset = queryset.filter(task__archived_at__isnull=True, task__parent__archived_at__isnull=True, task__project__archived_at__isnull=True, project__archived_at__isnull=True)
    if is_admin(viewer):
        return queryset
    if not is_team_member(viewer):
        from .collaboration import active_grants
        ids=active_grants(user_of(viewer)).values('project_id')
        return queryset.filter(Q(project_id__in=ids)|Q(task__project_id__in=ids))
    user = user_of(viewer)
    return queryset.filter(
        Q(author=user)
        | Q(task__project__owner=user) | Q(task__project__members=user)
        | Q(project__owner=user) | Q(project__members=user)
        | Q(status=Submission.ACCEPTED) | Q(is_final=True)
    ).distinct()


def can_view_claim(viewer, claim):
    """报销申请对全体团队成员可见（含待审、含他人申请），与团队账本可见性一致。

    普通用户与访客不是团队成员，看不到任何报销申请。
    `claim` 目前不参与判定，保留参数是为了与其它 `can_view_*` 判定保持一致的调用形式，
    也便于将来按单据状态再收窄。
    """
    return is_team_member(viewer) and (can_manage_finance(viewer) or claim.applicant_id == user_of(viewer).pk)


def can_download_attachment(viewer, attachment):
    """附件下载权限：按附件所属对象分别判断，绝不提供公开 URL。"""
    from .collaboration import project_of,participates
    project=project_of(attachment)
    if project and participates(user_of(viewer),project):return True
    if attachment.chat_message_id:
        message = attachment.chat_message
        user = user_of(viewer)
        if message.withdrawn_at or message.hidden_by.filter(pk=user.pk).exists():
            return False
        if message.room == ChatMessage.PRIVATE:
            return is_team_member(viewer) and user.pk in (message.author_id, message.recipient_id)
        return is_team_member(viewer)
    if attachment.experiment_id:
        return is_team_member(viewer)
    if is_admin(viewer):
        return True
    if not is_team_member(viewer):
        return False  # 普通用户看不到任何团队附件。
    if attachment.entry_id:
        # 账本对全体开发者可见，但作废记录只对管理员可见（与财务页一致）。
        return can_manage_finance(viewer) and attachment.entry.voided_at is None and attachment.entry.archived_at is None
    if attachment.claim_id:
        # 凭证跟随报销申请本身的可见性：团队成员都能看，包括他人待审申请的发票。
        return attachment.claim.archived_at is None and can_view_claim(viewer, attachment.claim)
    if attachment.comment_id:
        return True  # 留言对登录成员可见。
    submission = attachment.submission
    if submission is None:
        return False
    return can_view_submission(viewer, submission)


# --------------------------------------------------------------------------
# 聊天室
# --------------------------------------------------------------------------

def can_use_chat_room(viewer, room):
    """「公共讨论」限管理员与开发者；「公共聊天室」对所有登录用户开放。"""
    if not user_of(viewer).is_authenticated:
        return False
    if room == ChatMessage.PRIVATE:
        return False  # Private messages use the participant-checked messages module.
    from .tenancy import team_id, active_member, membership_for
    if room == ChatMessage.DEVELOPERS:
        return team_id() is not None and active_member(user_of(viewer))
    member=membership_for(user_of(viewer))
    return bool(member and member.active and not member.deleted_at and member.team.active)


def require_chat_room(viewer, room):
    if not can_use_chat_room(viewer, room):
        raise PermissionDenied('这个聊天室不对当前身份开放。')


def visible_chat_rooms(viewer):
    """当前身份能进的聊天室，按「公共讨论 → 公共聊天室」排列。"""
    labels = dict(ChatMessage.ROOMS)
    order = [ChatMessage.DEVELOPERS, ChatMessage.PUBLIC]
    return [(room, labels[room]) for room in order if can_use_chat_room(viewer, room)]


def can_work_task(viewer, task):
    user = user_of(viewer)
    from .collaboration import participates
    return (is_team_member(viewer) or participates(user,task.project)) and (is_admin(viewer) or task.project.owner_id == user.pk or
        (task.project.is_participant(user) and (task.assignee_id == user.pk or task.members.filter(pk=user.pk).exists())))
