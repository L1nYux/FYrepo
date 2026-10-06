"""Team scope shared by HTTP, background workers and trusted maintenance jobs."""
from contextvars import ContextVar
from contextlib import contextmanager
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models

# Legacy command-line integrations use the migrated original team. HTTP always
# replaces this value, including with None for an account without a membership.
_team = ContextVar('workbench_team', default=1)
_http = ContextVar('workbench_http', default=False)


def team_id():
    return _team.get()


@contextmanager
def scope(value, *, http=False):
    token = _team.set(getattr(value, 'pk', value))
    request_token = _http.set(http)
    try:
        yield
    finally:
        _http.reset(request_token)
        _team.reset(token)


def required_team_id():
    value = team_id()
    if value is None:
        raise PermissionDenied('请先创建或加入团队。')
    return value


def in_http():
    return _http.get()


def activate_request(request, user=None):
    from .models import Team, TeamMembership
    user = user or request.user
    if not user.is_authenticated:
        request.team = Team.objects.filter(pk=1, active=True).first()
    else:
        memberships = TeamMembership.objects.filter(user=user, active=True, deleted_at__isnull=True, team__active=True)
        ranked = memberships.annotate(guest_last=models.Case(
            models.When(role='guest', then=1), default=0, output_field=models.IntegerField()))
        selected = memberships.filter(team_id=request.session.get('workbench-team')).first() or ranked.order_by('guest_last', 'pk').first()
        request.team = selected.team if selected else None
        if selected:
            request.session['workbench-team'] = selected.team_id
    _team.set(request.team.pk if request.team else None)
    return request.team


def team_users(*, include_inactive=False, include_deleted=False, member_only=False):
    from django.contrib.auth import get_user_model
    from .models import TeamMembership
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
        if 'team' in kwargs or 'team_id' in kwargs:
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
                if not related.all_objects.filter(pk=pk, team_id=required_team_id()).exists():
                    raise ValidationError('关联记录不属于当前团队。')
            elif related and related._meta.label_lower == 'auth.user':
                from .models import TeamMembership
                if not TeamMembership.objects.filter(team_id=required_team_id(), user_id=getattr(value,'pk',value)).exists():
                    raise ValidationError('请选择本团队成员。')
        return super(TeamQuerySet, self.filter(team_id=required_team_id())).update(**kwargs)

    def delete(self):
        return super(TeamQuerySet, self.filter(team_id=required_team_id())).delete()

    def bulk_create(self, objs, **kwargs):
        objs = list(objs)
        for obj in objs:
            obj.validate_team()
        return super().bulk_create(objs, **kwargs)

    def bulk_update(self, objs, fields, **kwargs):
        if any(field in ('team', 'team_id') for field in fields):
            raise ValidationError('不能改变记录所属团队。')
        objs = list(objs)
        for obj in objs:
            obj.validate_team()
        return super().bulk_update(objs, fields, **kwargs)


class TeamManager(models.Manager.from_queryset(TeamQuerySet)):
    def get_queryset(self):
        query = super().get_queryset()
        return query.filter(team_id=team_id()) if team_id() is not None else query.none()


class TeamScopedModel(models.Model):
    team = models.ForeignKey('core.Team', on_delete=models.PROTECT, default=required_team_id, editable=False)
    objects = TeamManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True
        default_manager_name = 'objects'
        base_manager_name = 'objects'

    def validate_team(self):
        current = required_team_id()
        if self.team_id != current:
            raise PermissionDenied('记录不属于当前团队。')
        if self.pk and not self._state.adding and type(self).all_objects.filter(pk=self.pk).exclude(team_id=current).exists():
            raise PermissionDenied('不能改变记录所属团队。')
        for field in self._meta.fields:
            related = getattr(field, 'related_model', None)
            value = getattr(self, field.attname)
            if value is not None and related and issubclass(related, TeamScopedModel):
                if not related.all_objects.filter(pk=value, team_id=current).exists():
                    raise ValidationError('关联记录不属于当前团队。')
            elif value is not None and related and related._meta.label_lower == 'auth.user':
                from .models import TeamMembership
                if not TeamMembership.objects.filter(team_id=current, user_id=value).exists():
                    raise ValidationError('请选择本团队成员。')

    def save(self, *args, **kwargs):
        self.validate_team()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.team_id != required_team_id():
            raise PermissionDenied('记录不属于当前团队。')
        return super().delete(*args, **kwargs)
