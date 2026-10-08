"""Disposable fixtures use the same personal history boundary as HTTP requests."""
from core.models import Workspace
from core.tenancy import scope


def personal_scope(test,user):
    personal,_=Workspace.objects.get_or_create(owner=user,defaults={'kind':'personal'})
    context=scope(personal)
    context.__enter__()
    test.addCleanup(context.__exit__,None,None,None)
    return personal


def funded_model(user, **kwargs):
    from core.models import Team, TeamMembership
    from .models import Provider, PoolModel
    team = Team.objects.create(name='Worker billing', owner=user)
    TeamMembership.objects.create(team=team, user=user, role='owner')
    payer = Workspace.objects.create(kind='team', team=team)
    with scope(payer):
        provider = Provider.objects.create(name=kwargs.pop('name', 'Test'), base_url=kwargs.pop('base_url', 'https://example.com/v1'))
        return PoolModel.objects.create(provider=provider, **kwargs)
