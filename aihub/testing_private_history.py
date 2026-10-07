"""Disposable fixtures use the same personal history boundary as HTTP requests."""
from core.models import Workspace
from core.tenancy import scope


def personal_scope(test,user):
    personal,_=Workspace.objects.get_or_create(owner=user,defaults={'kind':'personal'})
    context=scope(personal)
    context.__enter__()
    test.addCleanup(context.__exit__,None,None,None)
    return personal
