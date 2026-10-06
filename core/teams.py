"""Account-level team selection and platform administration."""
import hashlib
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction, models
from django.db.models import Count, F
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from .models import Team, TeamMembership, Invite
from .tenancy import scope, activate_request
from . import permissions as perms


def valid_id(value):
    return value.isascii() and value.isdigit() and 0 < len(value) <= 18


@login_required
def index(request):
    memberships = TeamMembership.objects.filter(user=request.user, deleted_at__isnull=True).select_related('team').order_by('joined_at', 'pk')
    successors = TeamMembership.objects.filter(team=request.team, active=True, role__in=['admin','member'], deleted_at__isnull=True, user__is_active=True).exclude(user=request.user).select_related('user') if request.team and request.team.owner_id == request.user.pk else []
    return render(request, 'core/teams.html', {'memberships':memberships, 'team_successors':successors})


@login_required
@require_POST
def create(request):
    from .admission import create_from_invitation
    try:
        team=create_from_invitation(request.user, request.POST.get('code',''), request.POST.get('name',''))
    except ValidationError as error:
        messages.error(request, ' '.join(error.messages)); return redirect('teams')
    request.session['workbench-team']=team.pk
    messages.success(request, '团队已创建。')
    return redirect('workspace_home')


@login_required
@require_POST
def switch(request):
    if not valid_id(request.POST.get('team', '')):
        messages.error(request, '请选择有效团队。'); return redirect('teams')
    membership=get_object_or_404(TeamMembership, user=request.user, team_id=request.POST.get('team'), active=True, deleted_at__isnull=True, team__active=True)
    request.session['workbench-team']=membership.team_id
    request.session.pop(perms.SESSION_KEY, None)
    return redirect('workspace_home' if membership.role!='guest' else 'showcase')


@login_required
@require_POST
def join(request):
    from .admission import join_from_invitation
    try:
        team=join_from_invitation(request.user, request.POST.get('code',''))
    except ValidationError as error:
        messages.error(request,' '.join(error.messages)); return redirect('teams')
    request.session['workbench-team']=team.pk
    return redirect('workspace_home')


@login_required
@require_POST
def transfer(request):
    if not valid_id(request.POST.get('user', '')):
        messages.error(request, '请选择接任成员。'); return redirect('teams')
    with transaction.atomic():
        team=get_object_or_404(Team.objects.select_for_update(),pk=getattr(request.team,'pk',None),owner=request.user,active=True)
        target=get_object_or_404(TeamMembership.objects.select_for_update(),team=team,user_id=request.POST.get('user'),active=True,role__in=['admin','member'],deleted_at__isnull=True,user__is_active=True)
        if target.user_id==request.user.pk:
            messages.error(request,'请选择另一位团队成员。'); return redirect('teams')
        if request.POST.get('confirm') != team.name:
            messages.error(request,'请填写团队名称确认交接。'); return redirect('teams')
        TeamMembership.objects.filter(team=team,role='owner').update(role='admin')
        target.role='owner';target.save(update_fields=['role'])
        team.owner=target.user;team.save(update_fields=['owner'])
    messages.success(request,'团队所有权已交接。');return redirect('teams')


@login_required
def platform(request):
    from .team_permissions import can_manage_admission
    from .models import TeamCreationInvite
    from .pagination import page
    if not can_manage_admission(request): raise PermissionDenied('未获得软件管理权限。')
    fresh_code=None
    if request.method=='POST':
        action=request.POST.get('action')
        if action=='create_invite':
            try:
                capacity=int(request.POST.get('member_limit','10')); days=int(request.POST.get('days','7'))
                if not 1<=capacity<=1000 or not 1<=days<=90: raise ValueError
            except ValueError:
                messages.error(request,'成员上限须为 1–1000，有效期须为 1–90 天。')
            else:
                _invite,fresh_code=TeamCreationInvite.issue(request.user,capacity,days)
        elif action=='revoke_invite':
            if not valid_id(request.POST.get('invite','')): raise PermissionDenied
            invite=get_object_or_404(TeamCreationInvite,pk=request.POST.get('invite'),used_at__isnull=True)
            TeamCreationInvite.objects.filter(pk=invite.pk,used_at__isnull=True).update(revoked_at=timezone.now())
            return redirect('platform')
        elif action in ('enable','disable','capacity'):
            if not valid_id(request.POST.get('team','')): raise PermissionDenied
            with transaction.atomic():
                Team.objects.filter(pk=request.POST['team']).update(member_limit=F('member_limit'))
                target=get_object_or_404(Team.objects.select_for_update(),pk=request.POST['team'])
                if action=='capacity':
                    try:
                        capacity=int(request.POST.get('member_limit',''))
                        if not 1<=capacity<=1000: raise ValueError
                        # Serialize with concurrent admission before counting.
                        Team.objects.filter(pk=target.pk).update(member_limit=F('member_limit'))
                        count=TeamMembership.objects.filter(team=target,active=True,deleted_at__isnull=True).count()
                        if capacity<count: raise ValueError
                    except ValueError:
                        messages.error(request,'人数上限须为 1–1000，且不能小于现有在用成员数。')
                    else:
                        Team.objects.filter(pk=target.pk).update(member_limit=capacity)
                        messages.success(request,'团队人数上限已更新。')
                elif target.pk==1 and action=='disable':
                    messages.error(request,'原团队请通过运维流程停用。')
                else:
                    Team.objects.filter(pk=target.pk).update(active=action=='enable')
            return redirect('platform')
        else: raise PermissionDenied
    teams=Team.objects.select_related('owner').annotate(member_count=Count('memberships',filter=models.Q(memberships__active=True,memberships__deleted_at__isnull=True))).order_by('pk')
    return render(request,'core/platform.html',{'platform_teams':page(request,teams),
        'creation_invites':page(request,TeamCreationInvite.objects.select_related('used_by'),key='invites_page'),'fresh_code':fresh_code})


@login_required
@require_POST
def member_permissions(request, pk):
    perms.require_admin(request)
    from .team_permissions import CAPABILITIES
    member=get_object_or_404(TeamMembership,pk=pk,team=request.team,deleted_at__isnull=True)
    position=request.POST.get('position','').strip()
    capabilities=request.POST.getlist('permissions')
    if len(position)>60 or set(capabilities)-{key for key,_label in CAPABILITIES}:
        raise PermissionDenied('职务或权限设置无效。')
    TeamMembership.objects.filter(pk=member.pk,team=request.team).update(position=position,permissions=sorted(set(capabilities)))
    messages.success(request,'成员在本团队的职务与授权已保存。')
    return redirect('team_manage')
