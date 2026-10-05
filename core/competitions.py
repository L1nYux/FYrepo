from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q, Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import permissions as perms
from .pagination import page
from .forms import CompetitionForm
from .models import Competition, Submission, Task


def require_member(request):
    if not perms.is_team_member(request):
        raise PermissionDenied


@login_required
def index(request):
    require_member(request)
    live = Q(tasks__archived_at__isnull=True, tasks__project__archived_at__isnull=True,
             tasks__parent__archived_at__isnull=True)
    entries = Competition.objects.filter(archived_at__isnull=True).select_related('owner').annotate(
        task_count=Count('tasks', filter=live),
        completed_count=Count('tasks', filter=live & Q(tasks__status=Task.COMPLETED)))
    return render(request, 'core/competitions.html', {'entries': page(request,entries),
        'archived_competitions': Competition.objects.none()})


@login_required
def detail(request, pk):
    require_member(request)
    item = get_object_or_404(Competition.objects.select_related('owner'), pk=pk)
    tasks = Task.objects.filter(competition=item, archived_at__isnull=True,
                               project__archived_at__isnull=True, parent__archived_at__isnull=True).select_related('project', 'assignee')
    candidates = perms.visible_submissions(request, Submission.objects.filter(task__in=tasks).select_related('author', 'task', 'project'))
    selected_ids = set(item.final_results.values_list('pk', flat=True))
    if request.method == 'POST':
        perms.require_admin(request)
        if item.archived_at:
            raise PermissionDenied('比赛已归档，请先恢复。')
        chosen = request.POST.getlist('results')
        if any(not value.isdigit() for value in chosen):
            raise PermissionDenied('成果编号无效。')
        eligible = list(candidates.filter(pk__in=chosen))
        if len(eligible) != len(set(chosen)):
            raise PermissionDenied('只能选用本比赛关联任务的可见成果。')
        item.final_results.set(eligible)
        messages.success(request, '参赛成果已更新。')
        return redirect(reverse('competition_detail', args=[pk]) + '?tab=results')
    tab = 'results' if request.GET.get('tab') == 'results' else 'tasks'
    return render(request, 'core/competition_detail.html', {
        'item': item, 'tasks': tasks, 'competition_tab': tab, 'candidates': candidates,
        'selected_ids': selected_ids, 'selected_results': candidates.filter(pk__in=selected_ids),
        'can_manage': not item.archived_at and (perms.is_admin(request) or item.owner_id == request.user.pk),
    })


@login_required
def edit(request, pk=None):
    require_member(request)
    item = get_object_or_404(Competition, pk=pk, archived_at__isnull=True) if pk else None
    if not perms.is_admin(request) and (not item or item.owner_id != request.user.pk):
        raise PermissionDenied
    form = CompetitionForm(request.POST or None, instance=item,
                           initial={'owner': request.user.pk} if item is None else None)
    if not perms.is_admin(request):
        form.fields['owner'].disabled = True
    if request.method == 'POST' and form.is_valid():
        entry = form.save(commit=False)
        if not item:
            entry.created_by = request.user
        entry.save()
        return redirect('competition_detail', pk=entry.pk)
    return render(request, 'core/competition_form.html', {'form': form, 'item': item})


@login_required
@require_POST
def archive(request, pk):
    perms.require_admin(request)
    item = get_object_or_404(Competition, pk=pk)
    restoring = bool(item.archived_at)
    item.archived_at = None if restoring else timezone.now()
    item.save(update_fields=['archived_at'])
    messages.success(request, '比赛已恢复。' if restoring else '比赛已移到回收站，关联任务和成果保留。')
    if restoring:
        return redirect('competition_detail', pk=pk)
    return redirect('competitions')
