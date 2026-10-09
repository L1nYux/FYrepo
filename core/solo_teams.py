"""Closed one-member teams retain the former workspace and all record IDs."""
from django.apps import apps
from django.db import transaction
from .models import Workspace, Team, TeamMembership


def ensure(user):
    with transaction.atomic():
        space, _ = Workspace.objects.get_or_create(owner=user, defaults={'kind': 'personal'})
        if space.team_id:
            return space
        Workspace.objects.filter(pk=space.pk).update(active=space.active)
        space = Workspace.objects.select_for_update().get(pk=space.pk)
        if space.team_id:
            return space
        from .identity import nickname
        team, _ = Team.objects.get_or_create(solo_owner=user, defaults={
            'name': (nickname(user)[:90] or '我的')+'的团队', 'owner': user,
            'listed': False, 'recruitment_mode': 'closed', 'member_limit': 1})
        TeamMembership.objects.get_or_create(team=team,user=user,defaults={'role':'owner'})
        Workspace.objects.filter(pk=space.pk).update(kind='team',team=team)
        # Preserve workspace IDs, citations, files, balances and billing prices.
        for model in apps.get_models():
            names={field.name for field in model._meta.fields}
            if {'workspace','team'} <= names:
                model._base_manager.filter(workspace_id=space.pk,team_id__isnull=True).update(team_id=team.pk)
        from aihub.models import PoolSettings
        from .tenancy import scope
        space.refresh_from_db()
        with scope(space):
            PoolSettings.objects.get_or_create(defaults={'owner':user})
        return space
