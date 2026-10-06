"""Preserve explicit legacy CLI account provisioning; web membership is explicit."""
from django.conf import settings
from django.db.models.signals import post_save, m2m_changed
from django.dispatch import receiver
from django.core.exceptions import ValidationError
from .models import MemberProfile, Team, TeamMembership
from .tenancy import in_http, team_id, TeamScopedModel, required_team_id


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def legacy_account(sender, instance, **kwargs):
    if kwargs.get('created') is False:
        return
    if in_http() or team_id() != 1 or not Team.objects.filter(pk=1).exists():
        return
    profile = getattr(instance, 'member_profile', None)
    role = 'admin' if instance.is_staff else 'guest' if profile and profile.tier == 'normal' else 'member'
    if instance.is_active and instance.is_superuser:
        # Trusted initial CLI setup only; web-created accounts do not reach here.
        Team.objects.filter(pk=1, owner__isnull=True).update(owner=instance)
        if Team.objects.filter(pk=1, owner=instance).exists(): role='owner'
    membership, _ = TeamMembership.objects.get_or_create(team_id=1, user=instance, defaults={'role': role, 'active': instance.is_active})
    if membership.role != 'owner':
        TeamMembership.objects.filter(pk=membership.pk).update(role=role, active=instance.is_active)


@receiver(post_save, sender=MemberProfile)
def legacy_profile(sender, instance, **kwargs):
    if not in_http() and team_id() == 1:
        legacy_account(type(instance.user), instance.user)


@receiver(m2m_changed)
def same_team_links(sender, instance, action, reverse, model, pk_set, **kwargs):
    if action not in ('pre_add', 'pre_remove', 'pre_clear'):
        return
    if isinstance(instance, TeamScopedModel) and instance.team_id != required_team_id():
        raise ValidationError('不能修改其他团队的关联。')
    if not isinstance(instance, TeamScopedModel) and issubclass(model, TeamScopedModel):
        if pk_set and model.all_objects.filter(pk__in=pk_set).exclude(team_id=required_team_id()).exists():
            raise ValidationError('不能修改其他团队的关联。')
        if action == 'pre_clear':
            # Reverse account-wide clear() is unsafe; remove explicit scoped rows instead.
            raise ValidationError('请在当前团队逐项移除关联。')
    if action != 'pre_add' or not pk_set:
        return
    if isinstance(instance, TeamScopedModel) and issubclass(model, TeamScopedModel):
        if model.all_objects.filter(pk__in=pk_set, team_id=instance.team_id).count() != len(pk_set):
            raise ValidationError('不能关联其他团队的记录。')
    elif isinstance(instance, TeamScopedModel) and model._meta.label_lower == settings.AUTH_USER_MODEL.lower():
        if TeamMembership.objects.filter(team_id=instance.team_id, user_id__in=pk_set, deleted_at__isnull=True).count() != len(pk_set):
            raise ValidationError('请选择本团队成员。')
    elif issubclass(model, TeamScopedModel):
        for item in model.all_objects.filter(pk__in=pk_set):
            if isinstance(instance, TeamScopedModel) and item.team_id != instance.team_id:
                raise ValidationError('不能关联其他团队的记录。')
            if instance._meta.label_lower == settings.AUTH_USER_MODEL.lower() and not TeamMembership.objects.filter(team_id=item.team_id, user=instance, deleted_at__isnull=True).exists():
                raise ValidationError('请选择本团队成员。')
