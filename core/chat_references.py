"""Search and render chat links using the source record's access rules."""
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET

from . import permissions as perms
from .releases import bundled
from .models import Announcement, ChatReference, ExpenseClaim, Experiment, FinanceEntry, Task, Project, SharedDocument
from .resource_registry import RESOURCES

MODELS = {'project': Project, 'document': SharedDocument, 'task': Task, 'experiment': Experiment, 'entry': FinanceEntry,
          'claim': ExpenseClaim, 'announcement': Announcement}
LABELS = dict(ChatReference.KINDS)


def available(viewer, kind):
    """Use source permissions across teams; a chat's current team is not a search filter."""
    model=MODELS.get(kind)
    if model is None: raise Http404
    user=perms.user_of(viewer)
    if kind=='document':
        from .document_permissions import visible
        return visible(user).select_related('workspace')
    from .resource_navigation import records, spaces
    from .tenancy import scope
    from types import SimpleNamespace
    rows=records(model,SimpleNamespace(user=user,GET={}),filtered=False)
    if kind=='project': return rows.filter(archived_at__isnull=True)
    if kind=='task': return rows.filter(archived_at__isnull=True,project__archived_at__isnull=True,parent__archived_at__isnull=True)
    if kind=='experiment': return rows.filter(project__archived_at__isnull=True)
    if kind=='announcement': return rows.filter(is_published=True,deleted_at__isnull=True)
    managers=[]
    for workspace in spaces(user):
        with scope(workspace):
            if perms.can_manage_finance(user): managers.append(workspace.pk)
    if kind=='entry': return rows.filter(workspace_id__in=managers,archived_at__isnull=True)
    return rows.filter(Q(applicant=user)|Q(workspace_id__in=managers),archived_at__isnull=True)


def can_view(viewer, kind, obj):
    return obj is not None and available(viewer,kind).filter(pk=obj.pk).exists()


def card(kind, obj):
    title = obj.name if kind == 'project' else obj.title if kind in ('task', 'document', 'experiment', 'announcement') else obj.memo[:90]
    status = ''
    if kind == 'project':
        status = obj.workspace.name
    elif kind == 'document':
        status = obj.get_kind_display()
    elif kind == 'task':
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
            'status': obj.workspace.name+(' · '+status if status and status!=obj.workspace.name else ''), 'url': reverse('chat_reference_detail', args=[kind, obj.pk]),
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
    kind = request.GET.get('kind', 'task')
    kinds = ('entry', 'claim') if kind == 'finance' else (kind,)
    query = request.GET.get('q', '').strip()[:100]
    results = []
    for target in kinds:
        rows = available(request, target)
        if query:
            condition = Q()
            for field in RESOURCES[target]['search']:
                condition |= Q(**{field+'__icontains': query})
            identifier = query.removeprefix('#')
            if identifier.isascii() and identifier.isdigit() and len(identifier) <= 18:
                condition |= Q(pk=int(identifier))
            rows = rows.filter(condition)
        results.extend(card(target, obj) for obj in rows.order_by('-pk')[:20])
    return JsonResponse({'results': results})


@login_required
@require_GET
def detail(request, kind, pk):
    item = get_object_or_404(available(request, kind), pk=pk)
    if kind in ('project', 'document'):
        return redirect(reverse(RESOURCES[kind]['detail'], args=[item.pk]))
    from .collaboration import activate_record
    activate_record(request,item)
    if kind == 'task':
        return render(request,'core/shared_record.html', {'item':item,'kind':kind,'reference':card(kind,item),'files':[]})
    if kind == 'experiment':
        return render(request,'core/shared_record.html', {'item':item,'kind':kind,'reference':card(kind,item),'files':item.attachments.all()})
    return render(request, 'core/chat_reference_detail.html', {
        'server_release_version':bundled()['version'] if kind=='announcement' and item.release_version else '',
        'item': item, 'kind': kind, 'reference': card(kind, item),
        'files': item.attachments.all() if kind in ('entry', 'claim') else [],
    })
