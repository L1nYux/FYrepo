"""模板上下文：把生效角色交给所有模板，避免每个视图重复传一遍。

模板里用 `is_admin` / `is_developer` / `is_normal` / `role_label` 判断界面差异；
视图如果自己在上下文里传了同名变量，以视图为准（视图用的是同一个判定函数，不会矛盾）。
"""

from django.conf import settings

from . import permissions as perms
from .navigation import is_public_page


def email_mode(request):
    """是否在用控制台邮件后端。

    开发模式且未配置 SMTP 时，重置链接与验证码只打印到 runserver 控制台、不会真的发邮件。
    页面据此如实提示，避免出现「提示已发送但收不到」的困惑。
    """
    return {'email_console': settings.EMAIL_BACKEND.endswith('console.EmailBackend')}


def role(request):
    from aihub.permissions import is_pool_owner
    current = getattr(request, 'role', None)
    if current not in perms.RANK:
        current = perms.account_role(getattr(request, 'user', None))
    available = perms.allowed_login_roles(getattr(request, 'user', None))
    return {
        'role': current,
        'role_label': perms.role_label(current),
        'is_admin': current == perms.ADMIN,
        'is_developer': current == perms.DEVELOPER,
        'is_normal': current == perms.NORMAL,
        'home_url_name': perms.home_url_name(current),
        'available_roles': [],
        'can_manage_api':is_pool_owner(request),
    }


def shell(request):
    from django.conf import settings
    from .models import Project, Task
    enabled = request.user.is_authenticated and perms.account_role(request.user) != perms.NORMAL
    name = request.resolver_match.url_name if request.resolver_match else ''
    section = '项目管理'
    for prefix, label in [('api_pool','公共 API 池'),('api_manage','API 池管理'),('ai_assistant','AI 助手'),('workspace','公告栏'),('announcement','公告栏'),('experiment','实验库'),('finance','财务服务'),('claim','财务服务'),('profile','账户设置'),('public_profile_edit','账户设置'),('change_password','修改密码'),('messages','消息'),('chat','聊天室'),('competition','比赛'),('invites','邀请码'),('members','成员资料库'),('team_manage','团队管理'),('contact_edit','团队联系方式'),('recycle','回收站')]:
        if name.startswith(prefix): section = label; break
    if name.startswith(('password_reset', 'password_code')):
        section = '密码与安全'
    if is_public_page(name):
        section = '公开页面'
    public_page = is_public_page(name) or name in ('login','register')
    public_page = public_page or (name.startswith('password_reset') and not request.user.is_authenticated)
    enabled = enabled and not public_page
    from aihub.permissions import is_pool_owner
    api_management = name == 'api_manage' or (name == 'api_pool' and request.GET.get('scope') == 'team' and is_pool_owner(request))
    personal_usage = name == 'api_pool' and not api_management
    context = {'shell_enabled':enabled, 'shell_section':section, 'is_messages': name.startswith('messages'), 'is_assistant': name == 'ai_assistant',
               'is_api_management':api_management, 'is_personal_usage':personal_usage}
    desktop = getattr(settings, 'WORKBENCH_DESKTOP', False) or request.session.get('desktop_client', False)
    context.update(desktop_mode=desktop, desktop_settings_page=desktop and name in (
        'api_manage', 'profile', 'public_profile_edit', 'change_password', 'required_password_change', 'member_reset_password', 'member_delete', 'team_manage', 'members', 'invites', 'contact_edit', 'recycle_bin', 'permanently_delete'))
    if desktop and api_management:
        context['desktop_settings_page']=True
    if desktop and request.user.is_authenticated and name.startswith(('password_reset', 'password_code')):
        context['desktop_settings_page']=True
    if name == 'chat_reference_detail':
        context['shell_section'] = '公告栏' if request.resolver_match.kwargs.get('kind') == 'announcement' else '财务服务'
    if not enabled: return context
    from .messages import unread_counts, unread_payload
    context['unread_total'] = unread_payload(request.user, unread_counts(request.user, request))['total']
    if context['is_assistant'] or api_management or personal_usage: return context
    projects = list(Project.objects.filter(archived_at__isnull=True).order_by('-updated_at', '-pk')[:30])
    project_id = task_id = None
    pk = request.resolver_match.kwargs.get('pk') if request.resolver_match else None
    if name == 'project_detail': project_id = pk
    if name == 'task_detail' and pk:
        task_id = pk
        project_id = Task.objects.filter(pk=pk,archived_at__isnull=True,project__archived_at__isnull=True).values_list('project_id',flat=True).first()
    # Load task branches only for the selected project.
    mothers=[]
    if project_id:
        tasks=list(Task.objects.filter(project_id=project_id,archived_at__isnull=True,parent__archived_at__isnull=True).order_by('created_at', 'pk'))
        children={}
        for task in tasks:
            children.setdefault(task.parent_id,[]).append(task)
        mothers=children.get(None,[])
        for task in mothers:
            task.shell_children = children.get(task.pk, [])
            task.shell_expanded = task.pk == task_id or any(child.pk == task_id for child in task.shell_children)
    context.update(shell_projects=projects,shell_project_id=project_id,shell_task_id=task_id,shell_mothers=mothers)
    return context
