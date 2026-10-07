"""Attribute workspace mutations to a person without copying confidential values."""
from contextvars import ContextVar
from contextlib import contextmanager
from django.db.models.signals import post_save, pre_delete, m2m_changed
from django.dispatch import receiver

_actor = ContextVar('workspace_actor', default=None)


@contextmanager
def acting_as(user):
    token = _actor.set(user.pk if user and user.is_authenticated else None)
    try:
        yield
    finally:
        _actor.reset(token)


def record(model, workspace, object_id, action, fields=()):
    from .models import WorkspaceEvent, TeamMembership, Workspace
    actor = _actor.get()
    if actor is None or model.__name__ in ('UserPresence','ChatReadState'):
        return
    space = Workspace.objects.get(pk=workspace)
    membership = TeamMembership.objects.filter(team_id=space.team_id, user_id=actor).first() if space.team_id else None
    authority = {'role': membership.role, 'position': membership.position, 'permissions': membership.permissions} if membership else {'role': 'personal_owner' if space.owner_id == actor else 'service'}
    WorkspaceEvent.objects.create(workspace_id=workspace, actor_id=actor,
        object_type=model._meta.label_lower, object_id=str(object_id), action=action,
        authority=authority, fields=sorted(set(fields)))


@receiver(post_save)
def saved(sender, instance, created, raw=False, update_fields=None, **kwargs):
    from .tenancy import TeamScopedModel
    if not raw and issubclass(sender, TeamScopedModel) and sender.__name__ not in ('UserPresence','ChatReadState'):
        record(sender, instance.workspace_id, instance.pk, 'create' if created else 'update', update_fields or [])


@receiver(pre_delete)
def deleted(sender, instance, **kwargs):
    from .tenancy import TeamScopedModel
    if issubclass(sender, TeamScopedModel):
        record(sender, instance.workspace_id, instance.pk, 'delete')


@receiver(m2m_changed)
def links_changed(sender, instance, action, reverse, model, pk_set, **kwargs):
    from .tenancy import TeamScopedModel
    if action not in ('post_add','post_remove','post_clear'):return
    if isinstance(instance,TeamScopedModel):
        record(type(instance),instance.workspace_id,instance.pk,action, [sender._meta.model_name])
    elif issubclass(model,TeamScopedModel) and pk_set:
        for item in model.all_objects.filter(pk__in=pk_set):
            record(model,item.workspace_id,item.pk,action,[sender._meta.model_name])
