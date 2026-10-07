"""Document grants are independent of platform administration and team roles."""
from django.db.models import Q
from django.utils import timezone
from .models import SharedDocument, DocumentAccess, TeamMembership
from .resource_navigation import spaces


def related_project(document):
    return document.project or (document.task.project if document.task_id else document.experiment.project if document.experiment_id else None)


def member(user, document):
    return bool(document.workspace.team_id and TeamMembership.objects.filter(
        user=user, team_id=document.workspace.team_id, active=True, deleted_at__isnull=True,
        team__active=True, role__in=['owner','admin','member']).exists())


def visible(user, *, archived=False):
    if not user.is_authenticated or not user.is_active:
        return SharedDocument.objects.none()
    from .collaboration import active_grants
    project_ids = active_grants(user).values('project_id')
    membership_ids = spaces(user).values('pk')
    access = DocumentAccess.objects.filter(user=user, active=True).filter(
        Q(project_required=False) | Q(document__project_id__in=project_ids) | Q(document__task__project_id__in=project_ids)).filter(
        Q(membership_required=False) | Q(document__workspace_id__in=membership_ids)).values('document_id')
    condition = Q(workspace_id__in=membership_ids) | Q(pk__in=access) | Q(project_id__in=project_ids) | Q(task__project_id__in=project_ids) | Q(experiment__project_id__in=project_ids)
    # A private personal document is only visible to its owner and explicit grantees.
    result = SharedDocument.objects.filter(condition, workspace__active=True).filter(
        Q(workspace__team__isnull=True) | Q(workspace__team__active=True)).select_related(
        'workspace__team', 'created_by', 'current', 'project', 'task__project', 'competition', 'experiment__project')
    return result.filter(archived_at__isnull=not archived).distinct()


def grant(user, document):
    result = DocumentAccess.objects.filter(document=document, user=user, active=True).first()
    if result and result.membership_required and not member(user,document):
        return None
    if result and result.project_required:
        from .collaboration import active_grants
        project=related_project(document)
        if not project or not active_grants(user).filter(project=project).exists():return None
    return result


def manager(user, document, *, archived=False):
    if not user.is_authenticated or not user.is_active or not visible(user,archived=archived).filter(pk=document.pk).exists():
        return False
    if document.workspace.kind == 'personal':
        return document.workspace.owner_id == user.pk
    membership = TeamMembership.objects.filter(user=user,team_id=document.workspace.team_id,
        active=True,deleted_at__isnull=True,role__in=['owner','admin','member']).first()
    if not membership:
        return False
    project=related_project(document)
    return membership.role in ('owner','admin') or document.created_by_id==user.pk or bool(project and project.owner_id==user.pk)


def reviewer(user, document):
    access=grant(user,document)
    return manager(user,document) or bool(access and access.role=='reviewer')


def editor(user, document):
    if not visible(user).filter(pk=document.pk).exists():return False
    access=grant(user,document)
    return reviewer(user,document) or bool(access and access.role=='editor')


def commenter(user, document):
    access=grant(user,document)
    return editor(user,document) or member(user,document) or bool(access and access.role=='commenter')


def draft_visible(user, draft):
    if not visible(user).filter(pk=draft.document_id).exists():return False
    return draft.author_id==user.pk or reviewer(user,draft.document) or draft.state in ('submitted','merged','rejected','changes_requested')


def draft_editable(user, draft):
    return draft.author_id==user.pk and draft.state in ('draft','changes_requested') and visible(user).filter(pk=draft.document_id).exists() and editor(user,draft.document)
