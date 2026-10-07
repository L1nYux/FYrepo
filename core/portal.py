from .tenancy import team_users
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.http import FileResponse, Http404
from django.views.decorators.http import require_POST
from . import permissions as perms
from .team_permissions import allowed
from .pagination import page
from .forms import AnnouncementForm, ExperimentForm, PublicProfileForm, TeamContactForm
from .models import Announcement, Competition, Experiment, ExperimentTemplate, Attachment, PublicProfile, TeamContact, Project, Task, FinanceEntry, ExpenseClaim

def require_admin(request):
    perms.require_admin(request)

def manages(project, user):
    return perms.is_admin(user) or project.owner_id == user.pk

def live(task):
    return not task.archived_at and not task.project.archived_at and (not task.parent_id or not task.parent.archived_at)

def public_home(request):
    projects = Project.objects.filter( public_state='public', archived_at__isnull=True).order_by('-updated_at', '-pk')[:3]
    experiments = Experiment.objects.filter(visibility='public').order_by('-updated_at', '-pk')[:3]
    members = PublicProfile.objects.filter(is_public=True, user__in=team_users()).select_related('user__member_profile')[:4]
    return render(request, 'core/public_home.html', {'projects': projects, 'experiments': experiments, 'members': members})


def public_projects(request):
    projects = Project.objects.filter( public_state='public', archived_at__isnull=True).order_by('-updated_at', '-pk')
    return render(request, 'core/public_projects.html', {'projects': page(request, projects)})


def public_project_detail(request, pk):
    project = get_object_or_404(Project, pk=pk, public_state='public', archived_at__isnull=True)
    experiments = Experiment.objects.filter(project=project, visibility='public')
    return render(request, 'core/public_project_detail.html', {'project': project, 'experiments': page(request,experiments)})


def public_experiments(request):
    experiments = Experiment.objects.filter(visibility='public').select_related('project')
    query = request.GET.get('q', '').strip()[:100]
    if query:
        experiments = experiments.filter(Q(title__icontains=query) | Q(number__icontains=query) | Q(purpose__icontains=query))
    return render(request, 'core/public_experiments.html', {'experiments': page(request, experiments), 'query': query})


def public_experiment_detail(request, pk):
    experiment = get_object_or_404(Experiment, pk=pk, visibility='public')
    return render(request, 'core/public_experiment_detail.html', {'experiment': experiment})


def public_members(request):
    profiles = PublicProfile.objects.filter(is_public=True, user__in=team_users()).select_related('user__member_profile').order_by('display_name', 'user__username')
    # 成员公开信息与团队联系方式合并在一页;/contact/ 也指向这里(见 urls.py)。
    return render(request, 'core/public_members.html', {
        'profiles': page(request, profiles), 'contact': TeamContact.objects.all().first()})


@login_required
def contact_edit(request):
    require_admin(request)
    item, _ = TeamContact.objects.get_or_create()
    form = TeamContactForm(request.POST or None, instance=item)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, '团队联系方式已保存。')
        return redirect('contact_edit')
    return render(request, 'core/contact_edit.html', {'form': form})


@login_required
def announcement_edit(request, pk=None):
    from .team_permissions import require
    require(request, "announcements")
    item = get_object_or_404(Announcement, pk=pk) if pk else None
    if item and item.release_version: raise PermissionDenied('系统版本公告由发布信息生成。')
    form = AnnouncementForm(request.POST or None, instance=item)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('workspace_home')
    return render(request, 'core/announcement_form.html', {'form': form, 'item': item})


@login_required
def experiments(request):
    from .resource_navigation import records
    entries = records(Experiment, request).select_related('project', 'created_by')
    query = request.GET.get('q', '').strip()[:100]
    if query:
        entries = entries.filter(Q(title__icontains=query) | Q(number__icontains=query) |
            Q(purpose__icontains=query) | Q(procedure__icontains=query) |
            Q(parameters__icontains=query) | Q(batch__icontains=query) | Q(source_id__icontains=query))
    if request.GET.get('scope') == 'mine':
        entries = entries.filter(created_by=request.user)
    return render(request, 'core/experiments.html', {'entries': page(request, entries), 'query': query,
        'parameter_templates': ExperimentTemplate.objects.select_related('created_by')})


@login_required
def experiments_compare(request):
    ids = list(dict.fromkeys(request.GET.getlist('ids')))
    if len(ids) not in (2, 3) or any(not value.isdigit() for value in ids):
        messages.error(request, '请选择 2–3 条实验记录。')
        return redirect('experiments')
    from .resource_navigation import records as accessible_records
    records = list(accessible_records(Experiment, request, filtered=False).filter(pk__in=ids).select_related('project'))
    if len(records) != len(ids):
        raise Http404('实验记录不存在')
    return render(request, 'core/experiment_compare.html', {'records': records})


@login_required
@require_POST
def experiment_template_delete(request, pk):
    item = get_object_or_404(ExperimentTemplate, pk=pk)
    if not (perms.is_admin(request) or allowed(request,'experiments') or request.user.pk == item.created_by_id):
        raise PermissionDenied
    item.delete()
    messages.success(request, '模板已删除，实验记录保持原样。')
    return redirect('experiments')


@login_required
def experiment_detail(request, pk):
    from aihub.service import callable_experiments
    item = get_object_or_404(Experiment.objects.select_related('project', 'created_by'), pk=pk)
    can_edit = perms.is_admin(request) or allowed(request,'experiments') or request.user.pk == item.created_by_id or bool(item.project_id and manages(item.project, request.user))
    references = perms.visible_submissions(request, item.submissions.select_related('task', 'project', 'author'))
    return render(request, 'core/experiment_detail.html', {'item': item, 'tab': request.GET.get('tab','design') if request.GET.get('tab','design') in ('design','runs','data','results') else 'design', 'can_edit': can_edit, 'can_run': callable_experiments(request.user).filter(pk=item.pk).exists(), 'references': references, 'runs': page(request, item.runs.select_related('created_by').prefetch_related('attachments')), 'api_calls': page(request, item.api_calls.select_related('model__provider', 'user'), key='calls_page')})


@login_required
def experiment_edit(request, pk=None):
    item = get_object_or_404(Experiment, pk=pk) if pk else None
    if item and not (perms.is_admin(request) or allowed(request,'experiments') or request.user.pk == item.created_by_id or
                     (item.project_id and manages(item.project, request.user))):
        raise PermissionDenied
    task_id = request.POST.get('task') or request.GET.get('task')
    origin_task = get_object_or_404(Task, pk=task_id) if task_id else None
    if origin_task and (not live(origin_task) or not perms.can_work_task(request, origin_task)):
        raise PermissionDenied
    if item and origin_task and item.project_id != origin_task.project_id:
        raise PermissionDenied('已关联的记录不能移到其他项目。')
    project_id = request.POST.get('origin_project') or request.GET.get('project')
    origin_project = get_object_or_404(Project, pk=project_id, archived_at__isnull=True) if project_id else None
    if origin_project and not (perms.is_admin(request) or origin_project.is_participant(request.user)):
        raise PermissionDenied
    form = ExperimentForm(request.POST or None, request.FILES or None, instance=item, user=request.user,
                          initial={'project': origin_task.project.pk if origin_task else origin_project.pk} if (origin_task or origin_project) else None)
    if origin_task or origin_project:
        form.fields['project'].disabled = True

    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            was_public = bool(item and item.visibility == 'public')
            entry = form.save_record(origin_task=origin_task)
        messages.success(request, '实验记录已保存。已公开记录修改后需要重新审核。' if was_public else '实验记录已保存。')
        if origin_task:
            return redirect('task_detail', pk=origin_task.pk)
        if origin_project:
            return redirect('project_detail', pk=origin_project.pk)
        return redirect('experiment_detail', pk=entry.pk)
    return render(request, 'core/experiment_form.html', {'form': form, 'item': item, 'origin_task': origin_task, 'origin_project': origin_project,
        'experiment_presets': list(ExperimentTemplate.objects.values('id', 'name', 'parameters'))})


def public_experiment_file(request, pk):
    attachment = get_object_or_404(Attachment.objects.select_related('experiment'), pk=pk,
                                   experiment__visibility='public')
    try:
        return FileResponse(attachment.file.open('rb'), as_attachment=True, filename=attachment.original_name)
    except FileNotFoundError:
        raise Http404('文件不存在')


@login_required
@require_POST
def experiment_visibility(request, pk):
    with transaction.atomic():
        item = get_object_or_404(Experiment.objects.select_for_update(), pk=pk)
        action = request.POST.get('action')
        if action == 'request' and (request.user.pk == item.created_by_id or perms.is_admin(request) or
                                    (item.project_id and manages(item.project, request.user))):
            if item.visibility == 'internal':
                item.visibility = 'pending'
        elif action in ('publish', 'internal') and perms.is_admin(request):
            if action == 'publish' and (not item.procedure.strip() or not item.result.strip()):
                messages.error(request, '公开前请填写实验流程和结果。')
                return redirect('experiment_detail', pk=pk)
            item.visibility = 'public' if action == 'publish' else 'internal'
        else:
            raise PermissionDenied
        item.save(update_fields=['visibility', 'updated_at'])
    return redirect('experiment_detail', pk=pk)


@login_required
def public_profile_edit(request):
    item, _ = PublicProfile.objects.get_or_create(user=request.user)
    form = PublicProfileForm(request.POST or None, instance=item)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, '个人信息已保存。')
        return redirect('public_profile_edit')
    return render(request, 'core/public_profile_form.html', {'form': form, 'profile': item})


@login_required
@require_POST
def project_visibility(request, pk):
    from .team_permissions import allowed
    with transaction.atomic():
        project = get_object_or_404(Project.objects.select_for_update(), pk=pk)
        action = request.POST.get('action')
        if action == 'request' and manages(project, request.user):
            if project.public_state == 'internal':
                project.public_state = 'pending'
        elif action in ('publish', 'internal') and (perms.is_admin(request) or allowed(request,'projects')):
            if action == 'publish' and not project.public_summary.strip():
                messages.error(request, '请先填写公开项目简介。')
                return redirect('project_detail', pk=pk)
            project.public_state = 'public' if action == 'publish' else 'internal'
        else:
            raise PermissionDenied
        project.save(update_fields=['public_state', 'updated_at'])
    return redirect('project_detail', pk=pk)

@login_required
def workspace_home(request):
    from .releases import bundled
    from .models import TeamMembership
    count=TeamMembership.objects.filter(team=request.team,active=True,deleted_at__isnull=True).count()
    from .resource_navigation import records, create_spaces
    upcoming=records(Task,request).filter(Q(assignee=request.user)|Q(members=request.user),archived_at__isnull=True,project__archived_at__isnull=True,parent__archived_at__isnull=True).exclude(status=Task.COMPLETED).distinct().order_by('due_date','pk')[:6]
    from .team_permissions import allowed
    show_announcements=bool(request.team and request.workspace.kind=='team' and request.GET.get('ownership','all')!='all')
    can_publish=show_announcements and allowed(request,'announcements')
    announcements=page(request,records(Announcement,request).filter(is_published=True,release_version__isnull=True) if show_announcements else Announcement.all_objects.none())
    announcements.object_list=list(announcements.object_list)
    for item in announcements:item.can_edit=can_publish
    recent_projects=records(Project,request).filter(archived_at__isnull=True).order_by('-updated_at','-pk')[:4]
    return render(request, 'core/workspace_home.html', {'home_member_count':count,'home_tasks':upcoming,
        'home_show_announcements':show_announcements,'home_projects':recent_projects,
        'home_can_publish':can_publish,
        'announcements': announcements, 'server_release_version':bundled()['version']})

@login_required
def recycle_bin(request):
    if not perms.is_team_member(request): raise PermissionDenied
    projects = Project.objects.filter(archived_at__isnull=False)
    tasks = Task.objects.filter(archived_at__isnull=False).select_related('project', 'parent')
    competitions = Competition.objects.filter(archived_at__isnull=False)
    if not perms.is_admin(request):
        projects = projects.none()
        tasks = tasks.filter(project__owner=request.user)
        competitions = competitions.none()
    entries = FinanceEntry.objects.filter(archived_at__isnull=False) if perms.can_manage_finance(request) else FinanceEntry.objects.none()
    claims = ExpenseClaim.objects.filter(archived_at__isnull=False)
    if not perms.can_manage_finance(request): claims = claims.filter(applicant=request.user, status=ExpenseClaim.PENDING)
    return render(request, 'core/recycle_bin.html', {name:page(request,rows,key=name+'_page') for name,rows in [('projects',projects),('tasks',tasks),('competitions',competitions),('entries',entries),('claims',claims)]})

@login_required
@require_POST
def restore(request, kind, pk):
    if kind in ('finance', 'claim'):
        with transaction.atomic():
            model = FinanceEntry if kind == 'finance' else ExpenseClaim
            item = get_object_or_404(model.objects.select_for_update(), pk=pk, archived_at__isnull=False)
            if kind == 'finance' or not (perms.is_team_member(request) and item.applicant_id == request.user.pk and item.status == ExpenseClaim.PENDING):
                if not perms.can_manage_finance(request):raise PermissionDenied
            from .recycling import deletion_scope
            scope = deletion_scope(item, kind)
            FinanceEntry.objects.filter(pk__in=scope['entries']).update(archived_at=None)
            ExpenseClaim.objects.filter(pk__in=scope['claims']).update(archived_at=None)
        messages.success(request, '财务记录已恢复，统计已同步更新。')
        return redirect('recycle_bin')
    if kind == 'project':
        perms.require_admin(request)
        item = get_object_or_404(Project, pk=pk, archived_at__isnull=False)
    elif kind == 'task':
        item = get_object_or_404(Task, pk=pk, archived_at__isnull=False)
        perms.require_project_manager(request, item.project)
        if item.project.archived_at or (item.parent_id and item.parent.archived_at):
            messages.error(request, '请先恢复所属项目和母任务。')
            return redirect('recycle_bin')
    elif kind == 'competition':
        perms.require_admin(request)
        item = get_object_or_404(Competition, pk=pk, archived_at__isnull=False)
    else:
        raise PermissionDenied
    item.archived_at = None
    item.save(update_fields=['archived_at'] if kind == 'competition' else ['archived_at', 'updated_at'])
    messages.success(request, '已恢复。')
    return redirect('recycle_bin')


@login_required
def permanently_delete(request, kind, pk):
    if kind in ('finance','claim'):
        if not perms.can_manage_finance(request):raise PermissionDenied
    else:perms.require_admin(request)
    models = {'project': Project, 'task': Task, 'competition': Competition, 'finance': FinanceEntry, 'claim': ExpenseClaim}
    model = models.get(kind)
    if model is None: raise Http404
    if request.method not in ('GET', 'POST'):
        from django.http import HttpResponseNotAllowed
        return HttpResponseNotAllowed(['GET', 'POST'])
    from django.core import signing
    from django.core.exceptions import ValidationError
    from django.db.models.deletion import ProtectedError
    from django.db.models import F
    from .recycling import remove_contents, deletion_scope
    from .models import Submission, Comment
    item = get_object_or_404(model, pk=pk, archived_at__isnull=False)
    if request.method == 'GET':
        scope = deletion_scope(item, kind)
        token = signing.dumps({'user': request.user.pk, 'kind': kind, 'pk': pk, 'scope': scope}, salt='recycle-delete', compress=True)
        return render(request, 'core/delete_preview.html', {'item': item, 'kind': kind, 'scope': scope, 'confirmation': token,
            'affected_tasks': Task.objects.filter(pk__in=scope['tasks']).select_related('created_by'),
            'affected_submissions': Submission.objects.filter(pk__in=scope['submissions']).select_related('author'),
            'affected_comments': Comment.objects.filter(pk__in=scope['comments']).select_related('author'),
            'affected_files': Attachment.objects.filter(pk__in=scope['attachments'])})
    try:
        with transaction.atomic():
            model.objects.filter(pk=pk, archived_at__isnull=False).update(archived_at=F('archived_at'))
            item = get_object_or_404(model.objects.select_for_update(), pk=pk, archived_at__isnull=False)
            scope = deletion_scope(item, kind)
            confirmed = signing.loads(request.POST.get('confirmation', ''), salt='recycle-delete', max_age=600)
            if confirmed != {'user': request.user.pk, 'kind': kind, 'pk': pk, 'scope': scope}:
                raise ValidationError('内容已变化，请重新查看删除范围。')
            if request.POST.get('action') == 'archive_children':
                from django.utils import timezone
                Task.objects.filter(pk__in=scope['active']).update(archived_at=timezone.now(), updated_at=timezone.now())
                messages.success(request, '所含任务已移入回收站，请再次查看删除范围。')
                return redirect('permanently_delete', kind=kind, pk=pk)
            if request.POST.get('action') != 'delete' or request.POST.get('confirm') != 'yes':
                raise ValidationError('请先查看并确认删除范围。')
            remove_contents(item, kind, scope)
    except (ProtectedError, ValidationError, signing.BadSignature) as error:
        messages.error(request, ' '.join(error.messages) if isinstance(error, ValidationError) else '依赖仍在使用或确认已过期，请重新查看删除范围。')
        return redirect('permanently_delete', kind=kind, pk=pk)
    else:
        messages.success(request, '已彻底删除，无法从回收站恢复。')
    return redirect('recycle_bin')


def download(request):
    from django.conf import settings
    import re
    version = getattr(settings, 'WORKBENCH_DESKTOP_RELEASE', '')
    version = version if re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version) else ''
    release_root = 'https://github.com/L1nYux/FYrepo/releases'
    assets = []
    if version:
        base = release_root + '/download/v' + version + '/ResearchWorkbench-' + version
        assets = [
            {'label': 'Windows · 64 位', 'url': base + '-win-x64.exe'},
            {'label': 'macOS · Apple 芯片', 'url': base + '-mac-arm64.dmg'},
            {'label': 'macOS · Intel 芯片', 'url': base + '-mac-x64.dmg'},
        ]
    return render(request, 'core/download.html', {'desktop_version': version, 'desktop_assets': assets,
        'desktop_releases': release_root, 'server_address': request.build_absolute_uri('/').rstrip('/')})
