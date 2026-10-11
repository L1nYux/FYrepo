"""One authorized data contract for server-rendered and component work lists."""
from urllib.parse import urlencode

from django.db.models import Avg, Count, Q
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils.cache import patch_vary_headers

from .collaboration import active_grants
from .identity import nickname
from .models import Project, Task, summarise_progress
from .pagination import page
from .resource_navigation import create_spaces, records, spaces

CONTRACT = 'work-list-v1'


def list_data(request, kind):
    ownership = getattr(request, 'resource_ownership', 'all')
    query = request.GET.get('q', '').strip()[:100]
    mine = request.GET.get('mine') == '1' or kind == 'projects' and request.GET.get('scope') == 'mine'
    choices = Project.STATUS if kind == 'projects' else Task.STATUS
    status = request.GET.get('status', '')
    status = status if status in dict(choices) else ''
    category = request.GET.get('category', '') if kind == 'tasks' else ''
    category = category if category in dict(Task.CATEGORIES) else ''
    if kind == 'projects':
        rows = records(Project, request).filter(archived_at__isnull=True).select_related('owner__member_profile')
        if mine:
            rows = rows.filter(Q(owner=request.user) | Q(members=request.user) |
                Q(pk__in=active_grants(request.user).values('project_id'))).distinct()
        if query:
            rows = rows.filter(Q(name__icontains=query) | Q(goal__icontains=query))
        if status:
            rows = rows.filter(status=status)
        result = page(request, rows.order_by('-created_at', '-pk'))
        projects = list(result)
        ids = [value.pk for value in projects]
        tasks = records(Task, request).filter(project_id__in=ids, archived_at__isnull=True,
            project__archived_at__isnull=True, parent__archived_at__isnull=True)
        progress = summarise_progress(tasks.values_list('project_id', 'id', 'parent_id', 'progress'))
        open_counts = dict(tasks.exclude(status=Task.COMPLETED).values_list('project_id').annotate(total=Count('id')))
        members = set(Project.members.through.objects.filter(project_id__in=ids, user=request.user).values_list('project_id', flat=True))
        members.update(active_grants(request.user).filter(project_id__in=ids).values_list('project_id', flat=True))
        items = [{
            'id': value.pk, 'title': value.name, 'url': reverse('project_detail', args=[value.pk]),
            'owner': nickname(value.owner), 'ownership': value.workspace.name,
            'status': value.status, 'status_label': value.get_status_display(),
            'participant': value.owner_id == request.user.pk or value.pk in members,
            'progress': progress.get(value.pk, 0), 'open_tasks': open_counts.get(value.pk, 0),
        } for value in projects]
    else:
        rows = records(Task, request).filter(archived_at__isnull=True,
            project__archived_at__isnull=True, parent__archived_at__isnull=True
        ).select_related('project', 'assignee__member_profile', 'competition').annotate(
            child_progress=Avg('children__progress', filter=Q(children__archived_at__isnull=True)))
        if mine:
            rows = rows.filter(Q(assignee=request.user) | Q(members=request.user)).distinct()
        if query:
            rows = rows.filter(Q(title__icontains=query) | Q(project__name__icontains=query) | Q(competition__name__icontains=query))
        if status:
            rows = rows.filter(status=status)
        if category:
            rows = rows.filter(category=category)
        result = page(request, rows.order_by('due_date', 'created_at', 'pk'))
        items = [{
            'id': value.pk, 'title': value.title, 'url': reverse('task_detail', args=[value.pk]),
            'project': value.project.name, 'project_url': reverse('project_detail', args=[value.project_id]),
            'competition': value.competition.name if value.competition_id else '',
            'competition_url': reverse('competition_detail', args=[value.competition_id]) if value.competition_id else '',
            'owner': nickname(value.assignee), 'ownership': value.workspace.name,
            'level': value.level_display, 'category_label': value.get_category_display(),
            'due_date': value.due_date.isoformat() if value.due_date else '—', 'overdue': value.overdue,
            'progress': round(value.child_progress) if value.parent_id is None and value.child_progress is not None else value.progress,
            'status': value.status, 'status_label': value.get_status_display(),
        } for value in result]
    filters = {'ownership': str(ownership), 'q': query, 'mine': mine, 'status': status, 'category': category}
    params = {key: value for key, value in filters.items() if key != 'mine' and value}
    if mine:
        params['mine'] = '1'
    params['page'] = result.number
    path = reverse('dashboard' if kind == 'projects' else 'task_list')
    def address(number):
        return path + '?' + urlencode({**params, 'page': number})
    create_url = reverse('project_new' if kind == 'projects' else 'task_new')
    if ownership != 'all':
        create_url += '?' + urlencode({'ownership': ownership})
    destinations = create_spaces(request, 'projects')
    can_create = any(ownership == 'all' or str(value.pk) == str(ownership) for value in destinations)
    return {
        'contract': CONTRACT, 'account': str(request.user.pk), 'kind': kind,
        'url': address(result.number), 'items': items, 'filters': filters,
        'spaces': [{'id': str(value.pk), 'name': value.name} for value in spaces(request.user)],
        'statuses': [{'id': key, 'name': label} for key, label in choices],
        'categories': [{'id': key, 'name': label} for key, label in Task.CATEGORIES],
        'projects_url': reverse('dashboard'), 'tasks_url': reverse('task_list'),
        'create_url': create_url if can_create else '', 'can_create': can_create,
        'pagination': {'number': result.number, 'pages': result.paginator.num_pages,
            'total': result.paginator.count, 'previous': address(result.previous_page_number()) if result.has_previous() else '',
            'next': address(result.next_page_number()) if result.has_next() else ''},
    }


def render_list(request, kind):
    data = list_data(request, kind)
    if request.headers.get('X-Zhiyu-Component') == CONTRACT:
        response = JsonResponse(data)
    else:
        response = render(request, 'core/work_list.html', {'work_list': data})
    response['Cache-Control'] = 'private, no-store'
    patch_vary_headers(response, ['X-Zhiyu-Component'])
    return response
