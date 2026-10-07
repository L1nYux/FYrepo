"""Team scope shared by HTTP, background workers and trusted maintenance jobs."""
from contextvars import ContextVar
from contextlib import contextmanager
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models

# Legacy command-line integrations use the migrated original team. HTTP always
# replaces this value, including with None for an account without a membership.
_team = ContextVar('workbench_team', default=1)
_space = ContextVar('workbench_space', default=None)
_http = ContextVar('workbench_http', default=False)


def team_id():
    return _team.get()


@contextmanager
def scope(value, *, http=False):
    from .models import Workspace
    is_space = isinstance(value, Workspace)
    token = _team.set(value.team_id if is_space else getattr(value, 'pk', value))
    space_token = _space.set(value.pk if is_space else None)
    request_token = _http.set(http)
    try:
        yield
    finally:
        _http.reset(request_token)
        _space.reset(space_token)
        _team.reset(token)


def required_team_id():
    value = team_id()
    if value is None:
        raise PermissionDenied('请先创建或加入团队。')
    return value


def in_http():
    return _http.get()


def workspace_id():
    if _space.get() is not None:
        return _space.get()
    from .models import Workspace, Team
    selected = team_id()
    if selected is None or not Team.objects.filter(pk=selected).exists():
        return None
    resolved = Workspace.objects.get_or_create(team_id=selected, defaults={'kind': 'team'})[0].pk
    _space.set(resolved)
    return resolved


def required_workspace_id():
    value = workspace_id()
    if value is None:
        raise PermissionDenied('请先选择个人或团队空间。')
    return value


def personal_owner_id():
    from .models import Workspace
    return Workspace.objects.filter(pk=workspace_id(), kind='personal', active=True).values_list('owner_id', flat=True).first()


def activate_request(request, user=None):
    from .models import Team, TeamMembership, Workspace
    user = user or request.user
    request.workspace = None
    request.team = None
    if not user.is_authenticated:
        request.team = Team.objects.filter(pk=1, active=True).first()
        if request.team:
            request.workspace = Workspace.objects.get_or_create(team=request.team, defaults={'kind':'team'})[0]
    else:
        personal=Workspace.objects.get_or_create(owner=user,defaults={'kind':'personal'})[0]
        memberships = TeamMembership.objects.filter(user=user, active=True, deleted_at__isnull=True, team__active=True, role__in=['owner','admin','member'])
        chosen = request.session.get('workbench-space')
        selected = memberships.filter(team_id=chosen[5:]).first() if isinstance(chosen,str) and chosen.startswith('team:') and chosen[5:].isdigit() else None
        # Preserve the existing team's workspace on first upgrade only.
        if chosen is None:
            selected = memberships.filter(team_id=request.session.get('workbench-team')).first() or memberships.order_by('pk').first()
        if selected:
            request.team = selected.team
            request.workspace = Workspace.objects.get_or_create(team=request.team, defaults={'kind':'team'})[0]
            request.session['workbench-team'] = selected.team_id
            request.session['workbench-space'] = 'team:'+str(selected.team_id)
        else:
            request.workspace = personal
            request.session['workbench-space'] = 'personal'
            request.session.pop('workbench-team', None)
    _team.set(request.team.pk if request.team else None)
    _space.set(request.workspace.pk if request.workspace else None)
    return request.team


def team_users(*, include_inactive=False, include_deleted=False, member_only=False):
    from django.contrib.auth import get_user_model
    from .models import TeamMembership
    personal = personal_owner_id()
    if personal:
        return get_user_model().objects.filter(pk=personal, is_active=True)
    memberships = TeamMembership.objects.filter(team_id=team_id())
    if not include_deleted: memberships=memberships.filter(deleted_at__isnull=True)
    if member_only: memberships=memberships.filter(role__in=['owner','admin','member'])
    if not include_inactive:
        memberships = memberships.filter(active=True, team__active=True)
    users = get_user_model().objects.filter(pk__in=memberships.values('user_id'))
    return users if include_inactive else users.filter(is_active=True)


def membership_for(user):
    from .models import TeamMembership
    return TeamMembership.objects.filter(team_id=team_id(), user=user).first()


def active_member(user):
    membership = membership_for(user)
    return bool(user.is_active and membership and membership.active and
                not membership.deleted_at and membership.role != 'guest' and membership.team.active)


class TeamQuerySet(models.QuerySet):
    def update(self, **kwargs):
        if any(key in kwargs for key in ('team','team_id','workspace','workspace_id')):
            raise ValidationError('不能改变记录所属团队。')
        for name, value in kwargs.items():
            if value is None or hasattr(value, 'resolve_expression'):
                continue
            try:
                field = self.model._meta.get_field(name.removesuffix('_id'))
            except Exception:
                continue
            related = getattr(field, 'related_model', None)
            if related and issubclass(related, TeamScopedModel):
                pk = getattr(value, 'pk', value)
                if not related.all_objects.filter(pk=pk, workspace_id=required_workspace_id()).exists():
                    raise ValidationError('关联记录不属于当前团队。')
            elif related and related._meta.label_lower == 'auth.user':
                from .models import TeamMembership
                if not team_users(include_inactive=True).filter(pk=getattr(value,'pk',value)).exists():
                    from .collaboration import permits_record_user
                    if not all(permits_record_user(item,getattr(value,'pk',value)) for item in self):
                        raise ValidationError('请选择本团队成员或本项目的合作成员。')
        from django.db import transaction
        from .workspace_audit import record
        selected = self.filter(workspace_id=required_workspace_id())
        with transaction.atomic():
            # Acquire the SQLite writer lock before reading affected ids. A
            # read-then-write upgrade deadlocks competing quota/gift requests.
            primary_key = self.model._meta.pk.name
            super(TeamQuerySet, selected).update(**{primary_key: models.F(primary_key)})
            identifiers = list(selected.values_list('pk', flat=True))
            count = super(TeamQuerySet, selected).update(**kwargs)
            for identifier in identifiers:
                record(self.model, required_workspace_id(), identifier, 'update', kwargs.keys())
            return count

    def delete(self):
        return super(TeamQuerySet, self.filter(workspace_id=required_workspace_id())).delete()

    def bulk_create(self, objs, **kwargs):
        objs = list(objs)
        for obj in objs:
            obj.validate_team()
        from django.db import transaction
        from .workspace_audit import record
        with transaction.atomic():
            result=super().bulk_create(objs, **kwargs)
            for obj in result:
                if obj.pk:record(type(obj),obj.workspace_id,obj.pk,'create')
            return result

    def bulk_update(self, objs, fields, **kwargs):
        if any(field in ('team', 'team_id', 'workspace', 'workspace_id') for field in fields):
            raise ValidationError('不能改变记录所属团队。')
        objs = list(objs)
        for obj in objs:
            obj.validate_team()
        return super().bulk_update(objs, fields, **kwargs)


class TeamManager(models.Manager.from_queryset(TeamQuerySet)):
    def get_queryset(self):
        query = super().get_queryset()
        if _space.get() is not None:
            return query.filter(workspace_id=_space.get())
        return query.filter(workspace__team_id=team_id()) if team_id() is not None else query.none()


class TeamScopedModel(models.Model):
    team = models.ForeignKey('core.Team', on_delete=models.PROTECT, default=team_id, null=True, blank=True, editable=False)
    workspace = models.ForeignKey('core.Workspace', on_delete=models.PROTECT, default=required_workspace_id, editable=False)
    objects = TeamManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True
        default_manager_name = 'objects'
        base_manager_name = 'all_objects'

    def validate_team(self):
        current = required_workspace_id()
        if self.workspace_id != current or self.team_id != team_id():
            raise PermissionDenied('记录不属于当前团队。')
        if self.pk and not self._state.adding and type(self).all_objects.filter(pk=self.pk).exclude(workspace_id=current).exists():
            raise PermissionDenied('不能改变记录所属团队。')
        for field in self._meta.fields:
            related = getattr(field, 'related_model', None)
            value = getattr(self, field.attname)
            if value is not None and related and issubclass(related, TeamScopedModel):
                if not related.all_objects.filter(pk=value, workspace_id=current).exists():
                    raise ValidationError('关联记录不属于当前团队。')
            elif value is not None and related and related._meta.label_lower == 'auth.user':
                if self._meta.model_name == 'invite' and field.name == 'restricted_user':
                    continue  # Recruitment invite recipients have not joined yet.
                from .models import TeamMembership
                if not team_users(include_inactive=True).filter(pk=value).exists():
                    from .collaboration import permits_record_user
                    if not permits_record_user(self,value):
                        raise ValidationError('请选择本团队成员或本项目的合作成员。')

    def save(self, *args, **kwargs):
        self.validate_team()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.workspace_id != required_workspace_id():
            raise PermissionDenied('记录不属于当前团队。')
        return super().delete(*args, **kwargs)
