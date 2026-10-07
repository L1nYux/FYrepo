"""Project-only grants do not confer team, finance, or pool membership."""
from django.db.models import Q
from django.utils import timezone
from .models import ProjectCollaborator


def active_grants(user):
    return ProjectCollaborator.objects.filter(user=user,user__is_active=True,active=True,project__archived_at__isnull=True,project__workspace__active=True).filter(Q(expires_at__isnull=True)|Q(expires_at__gt=timezone.now())).filter(Q(project__team__isnull=True)|Q(project__team__active=True))


def participates(user,project):
    return bool(user.is_authenticated and active_grants(user).filter(project=project).exists())


def project_of(record):
    from .models import Project,Task,Submission,Attachment,Comment
    if isinstance(record,Project):return record
    if isinstance(record,Task):return record.project
    if isinstance(record,Submission):return record.owner_project
    if isinstance(record,Comment):
        if record.project_id:return record.project
        if record.task_id:return record.task.project
        if record.submission_id:return record.submission.owner_project
    if isinstance(record,Attachment):
        if record.submission_id:return record.submission.owner_project
        if record.comment_id:
            comment=record.comment
            if comment.project_id:return comment.project
            if comment.task_id:return comment.task.project
            if comment.submission_id:return comment.submission.owner_project
    return None


def permits_record_user(record,user_id):
    """Only project-bound participation fields may reference a collaborator."""
    project=project_of(record)
    return bool(project and project.pk and active_grants_user_id(user_id,project))


def active_grants_user_id(user_id,project):
    from django.contrib.auth import get_user_model
    user=get_user_model().objects.filter(pk=user_id,is_active=True).first()
    return bool(user and participates(user,project))


def activate_record(request,record):
    from .message_scope import select
    from .resource_navigation import spaces
    if spaces(request.user).filter(pk=record.workspace_id).exists():return select(request,record.workspace_id)
    project=project_of(record)
    if not project or not participates(request.user,project):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied('此项目的合作授权已失效。')
    from .tenancy import _space,_team
    from . import permissions
    request.workspace=record.workspace;request.team=record.workspace.team
    request.external_project_id=project.pk;request.role=permissions.NORMAL
    _space.set(record.workspace_id);_team.set(record.workspace.team_id)
    return record.workspace
