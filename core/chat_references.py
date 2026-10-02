"""Search and render chat links using the source record's access rules."""
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET

from . import permissions as perms
from .models import Announcement, ChatReference, ExpenseClaim, Experiment, FinanceEntry, Task

MODELS = {'task': Task, 'experiment': Experiment, 'entry': FinanceEntry,
          'claim': ExpenseClaim, 'announcement': Announcement}
LABELS = dict(ChatReference.KINDS)


def available(viewer, kind):
    """这一类记录中当前身份可检索的集合。

    报销申请对团队成员全开放（含他人待审申请），因此这里不再按申请人收窄；
    普通用户与访客不是团队成员，直接返回空集。
    """
    model = MODELS.get(kind)
    if model is None:
        raise Http404
    rows = model.objects.all()
    if not perms.is_team_member(viewer):
        return rows.none()
    if kind == 'task':
        return rows.filter(archived_at__isnull=True, project__archived_at__isnull=True,
                           parent__archived_at__isnull=True)
    if kind == 'entry' and not perms.is_admin(viewer):
        # 与财务页一致：作废记录对非管理员不可见（含其凭证）。
        return rows.filter(voided_at__isnull=True)
    if kind == 'announcement':
        return rows.filter(is_published=True)
    return rows


def can_view(viewer, kind, obj):
    if obj is None or not perms.is_team_member(viewer):
        return False
    if kind == 'task':
        return not (obj.archived_at or obj.project.archived_at or
                    (obj.parent_id and obj.parent.archived_at))
    if kind == 'claim':
        return perms.can_view_claim(viewer, obj)
    if kind == 'announcement':
        return obj.is_published
    return kind in ('experiment', 'entry')


def card(kind, obj):
    title = obj.title if kind in ('task', 'experiment', 'announcement') else obj.memo[:90]
    status = ''
    if kind == 'task':
        status = obj.get_status_display()
    elif kind == 'experiment':
        status = obj.number + ' · ' + obj.get_visibility_display()
    elif kind == 'entry':
        status = ('已作废 · ' if obj.voided_at else '') + obj.get_kind_display() + f' · ¥ {obj.amount}'
    elif kind == 'claim':
        status = obj.get_status_display() + f' · ¥ {obj.amount}'
    elif kind == 'announcement':
        status = obj.created_at.strftime('%Y-%m-%d')
    return {'key': f'{kind}:{obj.pk}', 'label': LABELS[kind], 'title': title,
            'status': status, 'url': reverse('chat_reference_detail', args=[kind, obj.pk]),
            'available': True}


def display(reference, viewer):
    obj = getattr(reference, reference.kind, None)
    if not can_view(viewer, reference.kind, obj):
        # Even the title, amount and original id are withheld from other viewers.
        return {'label': '引用内容', 'title': '内容已不可用或你无权查看',
                'status': '', 'url': '', 'available': False}
    return card(reference.kind, obj)


@login_required
@require_GET
def search(request):
    if not perms.is_team_member(request):
        raise Http404
    kind = request.GET.get('kind', 'task')
    kinds = ('entry', 'claim') if kind == 'finance' else (kind,)
    query = request.GET.get('q', '').strip()[:100]
    results = []
    for target in kinds:
        rows = available(request, target)
        if query:
            if target == 'experiment':
                rows = rows.filter(Q(title__icontains=query) | Q(number__icontains=query))
            elif target in ('entry', 'claim'):
                rows = rows.filter(memo__icontains=query)
            else:
                rows = rows.filter(title__icontains=query)
        results.extend(card(target, obj) for obj in rows.order_by('-pk')[:20])
    return JsonResponse({'results': results})


@login_required
@require_GET
def detail(request, kind, pk):
    item = get_object_or_404(available(request, kind), pk=pk)
    if kind == 'task':
        return redirect('task_detail', pk=pk)
    if kind == 'experiment':
        return redirect('experiment_detail', pk=pk)
    return render(request, 'core/chat_reference_detail.html', {
        'item': item, 'kind': kind, 'reference': card(kind, item),
        'files': item.attachments.all() if kind in ('entry', 'claim') else [],
    })
