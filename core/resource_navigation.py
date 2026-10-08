"""Account-wide discovery; writes still use a single authorized workspace."""
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404
from .models import Workspace, TeamMembership


def spaces(user):
    if not user.is_authenticated:
        return Workspace.objects.none()
    teams = TeamMembership.objects.filter(user=user, active=True, deleted_at__isnull=True,
        team__active=True, role__in=['owner', 'admin', 'member']).values('team_id')
    return Workspace.objects.filter(Q(kind='personal', owner=user) | Q(kind='team', team_id__in=teams), active=True).select_related('team')


def records(model, request, *, filtered=True):
    accessible = spaces(request.user)
    chosen = request.GET.get('ownership', 'all') if filtered else 'all'
    if chosen != 'all':
        if not chosen.isascii() or not chosen.isdigit() or len(chosen) > 18:
            raise PermissionDenied('归属筛选无效。')
        if not accessible.filter(pk=chosen).exists():
            raise PermissionDenied('无权访问该归属。')
        accessible = accessible.filter(pk=chosen)
    condition=Q(workspace_id__in=accessible.values('pk'))
    if chosen=='all':
        from .collaboration import active_grants
        ids=active_grants(request.user).values('project_id')
        paths={'Project':['pk'],'Task':['project_id'],'Submission':['project_id','task__project_id'],'Attachment':['submission__project_id','submission__task__project_id','comment__project_id','comment__task__project_id','comment__submission__project_id','comment__submission__task__project_id']}
        for path in paths.get(model.__name__,[]):condition|=Q(**{path+'__in':ids})
    return model.all_objects.filter(condition).select_related('workspace__team').distinct()


def activate(request):
    """Resolve object ownership before permission decorators; never change session."""
    if not request.user.is_authenticated or not request.resolver_match:
        return
    from . import models
    from .message_scope import select
    match = request.resolver_match
    name, kwargs = match.url_name or '', match.kwargs
    if match.namespace == 'sampling':
        from sampling.models import SamplingRun
        if kwargs.get('pk'):
            record = get_object_or_404(SamplingRun.objects.filter(workspace__in=spaces(request.user)), pk=kwargs['pk'])
            select(request, record.workspace_id)
        else:
            identifier = request.POST.get('ownership') or request.GET.get('ownership')
            project_id = request.POST.get('project')
            if project_id:
                if not project_id.isascii() or not project_id.isdigit() or len(project_id)>18:
                    # The form reports invalid project input; never query an unbounded id.
                    project_id = None
                project = models.Project.all_objects.filter(pk=project_id,workspace__in=spaces(request.user)).first() if project_id else None
                if project and not identifier:
                    identifier = project.workspace_id
            if identifier and identifier != 'all':
                select(request, identifier)
        request.resource_scoped = True
        return
    if name.startswith('me_') or name=='talent_profile':
        select(request, spaces(request.user).get(kind='personal').pk)
        request.resource_scoped = True
        return
    assistant_views=('ai_assistant','ai_start','ai_conversations','ai_conversation','ai_job','ai_image','ai_upload_image','ai_references','ai_web_preview')
    if name in assistant_views:
        # Personal history remains available after removal from a funding team.
        select(request,spaces(request.user).get(kind='personal').pk)
        request.resource_scoped=True
        return
    if name in ('ai_conversation','ai_job','ai_image'):
        from aihub.models import AssistantConversation,AssistantJob,AssistantImage
        model={'ai_conversation':AssistantConversation,'ai_job':AssistantJob,'ai_image':AssistantImage}[name]
        record=get_object_or_404(records(model,request,filtered=False),pk=kwargs['pk'])
        select(request,record.workspace_id);request.resource_scoped=True;return
    mapping = {'project_': models.Project, 'task_': models.Task, 'competition_': models.Competition,
        'experiment_': models.Experiment, 'submission_': models.Submission,
        'finance_': models.FinanceEntry, 'claim_': models.ExpenseClaim, 'announcement_':models.Announcement}
    record = None
    if kwargs.get('pk'):
        for prefix, model in mapping.items():
            if name.startswith(prefix) and name not in ('experiment_template_delete',):
                record = get_object_or_404(records(model, request, filtered=False), pk=kwargs['pk'])
                break
        if name == 'experiment_template_delete':
            record = get_object_or_404(records(models.ExperimentTemplate, request, filtered=False), pk=kwargs['pk'])
        if name == 'attachment_download' and not request.GET.get('space'):
            record = get_object_or_404(records(models.Attachment, request, filtered=False), pk=kwargs['pk'])
        if name in ('restore','permanently_delete'):
            model={'project':models.Project,'task':models.Task,'competition':models.Competition,
                   'finance':models.FinanceEntry,'claim':models.ExpenseClaim}.get(kwargs.get('kind'))
            if model:
                record=get_object_or_404(records(model,request,filtered=False),pk=kwargs['pk'])
                request.resource_scoped=True
    if record:
        from .collaboration import activate_record
        activate_record(request,record)
        if name.startswith(('finance_', 'claim_')):
            request.resource_scoped = True
        return
    if name == 'ai_assistant' and request.GET.get('kind') and request.GET.get('id'):
        context_models = {'project': models.Project, 'task': models.Task,
            'competition': models.Competition, 'experiment': models.Experiment,
            'submission': models.Submission}
        context_model = context_models.get(request.GET['kind'])
        identifier = request.GET['id']
        if context_model is None or not identifier.isascii() or not identifier.isdigit() or len(identifier) > 18:
            raise PermissionDenied('助手关联资料无效。')
        record = get_object_or_404(records(context_model, request, filtered=False), pk=identifier)
        select(request, record.workspace_id)
        request.resource_scoped = True
        return
    if name=='recycle_bin':
        identifier=request.GET.get('ownership')
        if identifier and identifier!='all':select(request,identifier)
        request.resource_scoped=True
    elif name=='workspace_home' and request.GET.get('ownership') not in (None,'all'):
        select(request,request.GET['ownership'])
    elif name=='announcement_new':
        identifier=request.POST.get('ownership') or request.GET.get('ownership')
        choices=[space for space in create_spaces(request,'announcements') if space.kind=='team']
        if identifier:select(request,identifier)
        elif choices:select(request,choices[0].pk)
        else:raise PermissionDenied('需要团队公告发布权限。')
    elif name in ('project_new', 'competition_new', 'experiment_new', 'task_new'):
        source = request.POST.get('task') or request.GET.get('task')
        project = request.POST.get('origin_project') or request.POST.get('project') or request.GET.get('project')
        for identifier in (source,project):
            if identifier and (not identifier.isascii() or not identifier.isdigit() or len(identifier)>18):
                raise PermissionDenied('关联记录无效。')
        if source:
            record = get_object_or_404(records(models.Task, request, filtered=False), pk=source)
        elif project:
            record = get_object_or_404(records(models.Project, request, filtered=False), pk=project)
        if record:
            from .collaboration import activate_record
            activate_record(request,record)
            return
        identifier = request.POST.get('ownership') or request.GET.get('ownership')
        if identifier:
            select(request, identifier)
        else:
            select(request, spaces(request.user).get(kind='personal').pk)
    elif name=='api_catalog' and request.GET.get('funding'):
        select(request,spaces(request.user).get(kind='personal').pk)
    elif name in ('finance_list', 'finance_new', 'claim_list', 'claim_new', 'api_pool', 'api_manage', 'api_discover', 'api_enable_models', 'api_model_price', 'api_catalog', 'api_usage', 'api_preferences', 'api_provider_quota','ai_assistant','ai_start','ai_conversations','ai_upload_image','ai_references','ai_web_preview'):
        request.resource_scoped=True
        identifier=request.POST.get('ownership') or request.GET.get('ownership')
        if identifier and identifier!='all':select(request, identifier)
        elif name in ('finance_list', 'finance_new', 'claim_list', 'claim_new', 'api_pool', 'api_manage','ai_assistant','ai_start','ai_conversations','ai_upload_image','ai_references','ai_web_preview'):
            select(request, spaces(request.user).get(kind='personal').pk)


def qualify_response(request, response):
    """Keep ledger/pool redirects in their explicit owner, without session writes."""
    if getattr(request,'resource_scoped',False) and response.has_header('Location'):
        from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
        target=urlsplit(response['Location'])
        if getattr(request,'personal_api',False) and not target.netloc and target.path.startswith('/api-pool/'):
            query=dict(parse_qsl(target.query));query.pop('ownership',None)
            query['tab']='connections' if target.path.startswith('/api-pool/manage/') else 'usage'
            if query['tab']=='usage':query['funding']=str(request.workspace.pk)
            response['Location']='/me/api/?'+urlencode(query)
            return response
        if not target.netloc and target.path.startswith(('/api-pool/','/finance/','/assistant/','/recycle-bin/')):
            query=dict(parse_qsl(target.query));query['ownership']=str(request.workspace.pk)
            response['Location']=urlunsplit((target.scheme,target.netloc,target.path,urlencode(query),target.fragment))
    return response


def create_spaces(request, capability):
    """Creating working records does not require team management privileges."""
    from .team_permissions import allowed
    from .tenancy import scope
    result = []
    for space in spaces(request.user):
        with scope(space):
            if space.kind == 'personal' or capability in ('experiments','documents') or allowed(request.user, capability):
                result.append(space)
    return result
