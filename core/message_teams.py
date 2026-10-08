"""Organization management inside Messages, with its own remembered selection."""
from functools import wraps
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.urls import reverse
from .models import TeamMembership, Workspace, TeamApplication
from .tenancy import scope
from . import permissions as perms


ROUTES={'/manage/':'/messages/teams/','/manage/members/':'/messages/teams/members/',
        '/manage/invites/':'/messages/teams/invites/','/manage/recruitment/':'/messages/teams/recruitment/',
        '/manage/recruitment/applications/':'/messages/teams/review/','/teams/':'/messages/teams/','/manage/members/':'/messages/teams/members/'}


def organization(view):
    @login_required
    @wraps(view)
    def wrapped(request,*args,**kwargs):
        memberships=TeamMembership.objects.filter(user=request.user,active=True,deleted_at__isnull=True,team__active=True,role__in=['owner','admin','member']).select_related('team')
        explicit=request.POST.get('message_team') or request.GET.get('team')
        selected=explicit or request.session.get('workbench-team')
        valid=selected and str(selected).isascii() and str(selected).isdigit() and len(str(selected))<=18
        chosen=memberships.filter(team_id=selected).first() if valid else None
        if explicit and not chosen:raise PermissionDenied('你已无权访问所选团队，请从团队列表重新选择。')
        chosen=chosen or memberships.filter(team=getattr(request,'team',None)).first() or memberships.first()
        if not chosen:
            if request.method!='GET':raise PermissionDenied('请先加入团队。')
            return render(request,'core/message_teams.html',{'message_memberships':memberships,'current_team':None})
        request.session['message-team']=chosen.team_id
        request.session['workbench-team']=chosen.team_id
        request.session['workbench-space']='team:'+str(chosen.team_id)
        request.team=chosen.team
        request.workspace=Workspace.objects.get_or_create(team=chosen.team,defaults={'kind':'team'})[0]
        with scope(request.workspace,http=True):
            request.role=perms.account_role(request.user)
            response=view(request,*args,**kwargs)
            if response.has_header('Location'):
                location=response['Location']
                if location in ROUTES:
                    still_member=memberships.filter(team_id=chosen.team_id).exists()
                    if not still_member:request.session.pop('message-team',None)
                    response['Location']=ROUTES[location]+('?team='+str(chosen.team_id) if still_member else '')
            return response
    return wrapped


@organization
def index(request):
    memberships=TeamMembership.objects.filter(user=request.user,active=True,deleted_at__isnull=True,team__active=True,role__in=['owner','admin','member']).select_related('team')
    from .team_permissions import allowed
    from .models import Announcement
    tab='settings' if request.GET.get('tab')=='settings' else 'overview'
    return render(request,'core/message_teams.html' if tab=='settings' or not request.team else 'core/team_overview.html',{'message_memberships':memberships,'team_tab':tab,
        'team_notices':Announcement.objects.filter(is_published=True).order_by('-created_at','-pk')[:10],
        'team_successors':TeamMembership.objects.filter(team=request.team,active=True,deleted_at__isnull=True,user__is_active=True,role__in=['admin','member']).exclude(user=request.user).select_related('user'),
        'message_team_members':TeamMembership.objects.filter(team=request.team,active=True,deleted_at__isnull=True).select_related('user'),
        'message_team_capabilities':__import__('core.team_permissions',fromlist=['CAPABILITIES']).CAPABILITIES,
        'pending_applications':TeamApplication.objects.filter(opening__team=request.team,state='pending').count() if allowed(request,'recruitment') else 0})


@organization
def review(request):
    from .recruitment import review
    return review(request)


@organization
def recruitment(request):
    from .recruitment import manage
    return manage(request)


@organization
def members(request):
    from .views import members
    return members(request)


@organization
def invites(request):
    from .views import invites
    return invites(request)


@organization
def permissions(request,pk):
    from .teams import member_permissions
    return member_permissions(request,pk)


@organization
def rename(request):
    from .teams import rename
    return rename(request)


@organization
def transfer(request):
    from .teams import transfer
    return transfer(request)


@organization
def leave(request):
    from .teams import leave
    return leave(request)


@organization
def disband(request):
    from .teams import disband
    return disband(request)


@organization
def remove_member(request,pk):
    from .member_management import delete_account
    return delete_account(request,pk)
