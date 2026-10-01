"""模板上下文：把生效角色交给所有模板，避免每个视图重复传一遍。

模板里用 `is_admin` / `is_developer` / `is_normal` / `role_label` 判断界面差异；
视图如果自己在上下文里传了同名变量，以视图为准（视图用的是同一个判定函数，不会矛盾）。
"""

from . import permissions as perms


def role(request):
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
    }


def shell(request):
    from .models import Project, Task
    enabled = request.user.is_authenticated and perms.account_role(request.user) != perms.NORMAL
    name = request.resolver_match.url_name if request.resolver_match else ''
    section = '项目管理'
    for prefix, label in [('workspace','公告栏'),('announcement','公告栏'),('experiment','实验库'),('finance','财务服务'),('claim','财务服务'),('profile','账户设置'),('public_profile_edit','账户设置'),('change_password','修改密码'),('messages','消息'),('chat','聊天室'),('competition','比赛'),('invites','邀请码'),('members','团队成员'),('team_manage','团队管理'),('contact_edit','团队联系方式'),('recycle','回收站')]:
        if name.startswith(prefix): section = label; break
    if (name.startswith('public_') and name != 'public_profile_edit') or name in ('contact','showcase','about'):
        section = '公开页面'
    public_page = (name.startswith('public_') and name != 'public_profile_edit') or name in ('contact','showcase','about','login','register')
    enabled = enabled and not public_page
    context = {'shell_enabled':enabled, 'shell_section':section, 'is_messages': name.startswith('messages')}
    if name == 'chat_reference_detail':
        context['shell_section'] = '公告栏' if request.resolver_match.kwargs.get('kind') == 'announcement' else '财务服务'
    if not enabled: return context
    from .messages import unread_counts
    context['unread_total'] = sum(unread_counts(request.user).values())
    projects = list(Project.objects.filter(archived_at__isnull=True).order_by('-updated_at')[:30])
    project_id = task_id = None
    pk = request.resolver_match.kwargs.get('pk') if request.resolver_match else None
    if name == 'project_detail': project_id = pk
    if name == 'task_detail' and pk:
        task_id = pk
        project_id = Task.objects.filter(pk=pk,archived_at__isnull=True,project__archived_at__isnull=True).values_list('project_id',flat=True).first()
    # Load task branches only for the selected project.
    mothers=[]
    if project_id:
        tasks=list(Task.objects.filter(project_id=project_id,archived_at__isnull=True,parent__archived_at__isnull=True).order_by('created_at'))
        children={}
        for task in tasks:
            children.setdefault(task.parent_id,[]).append(task)
        mothers=children.get(None,[])
        for task in mothers:
            task.shell_children = children.get(task.pk, [])
            task.shell_expanded = task.pk == task_id or any(child.pk == task_id for child in task.shell_children)
    context.update(shell_projects=projects,shell_project_id=project_id,shell_task_id=task_id,shell_mothers=mothers)
    return context
