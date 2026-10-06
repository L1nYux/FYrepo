"""Account-level team selection and platform administration."""
import hashlib
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
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
    name = request.POST.get('name', '').strip()
    if not name or len(name)>100:
        messages.error(request, '请填写 1–100 字的团队名称。');return redirect('teams')
    with transaction.atomic():
        get_user_model().objects.filter(pk=request.user.pk).update(is_active=F('is_active'))
        if Team.objects.filter(owner=request.user, active=True).count()>=5:
            messages.error(request, '最多创建 5 个在用团队。');return redirect('teams')
        team = Team.objects.create(name=name, owner=request.user)
        TeamMembership.objects.create(team=team, user=request.user, role='owner')
        with scope(team):
            from aihub.models import PoolSettings
            from .models import TeamContact
            PoolSettings.objects.create(owner=request.user)
            TeamContact.objects.create()
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
    code=request.POST.get('code','').strip()
    if not code or len(code)>100:
        messages.error(request,'请填写有效邀请码。');return redirect('teams')
    digest=hashlib.sha256(code.encode()).hexdigest()
    with transaction.atomic():
        get_user_model().objects.filter(pk=request.user.pk).update(is_active=F('is_active'))
        invite=Invite.all_objects.select_for_update().filter(code_hash=digest,used_at__isnull=True,revoked_at__isnull=True,expires_at__gt=timezone.now(),team__active=True).first()
        if not invite:
            messages.error(request,'邀请码无效、已使用或已过期。');return redirect('teams')
        membership=TeamMembership.objects.filter(team_id=invite.team_id,user=request.user).first()
        if membership:
            # Removal/suspension is not bypassed by redeeming another invite.
            messages.error(request,'你已有该团队的成员记录，请联系团队管理员恢复权限。');return redirect('teams')
        TeamMembership.objects.create(team_id=invite.team_id,user=request.user,role='member')
        with scope(invite.team_id):
            invite.used_by=request.user;invite.used_at=timezone.now();invite.save(update_fields=['used_by','used_at'])
    request.session['workbench-team']=invite.team_id
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
    if not perms.is_platform_admin(request):raise PermissionDenied('仅软件管理员可访问。')
    if request.method=='POST':
        if not valid_id(request.POST.get('team', '')): raise PermissionDenied('请选择有效团队。')
        target=get_object_or_404(Team,pk=request.POST.get('team'))
        action=request.POST.get('action')
        if action not in ('enable','disable'):raise PermissionDenied
        if target.pk==1 and action=='disable':
            messages.error(request,'原团队请通过运维流程停用，避免影响旧客户端。')
        else:
            Team.objects.filter(pk=target.pk).update(active=action=='enable')
            messages.success(request,'团队状态已更新。')
        return redirect('platform')
    teams=Team.objects.select_related('owner').annotate(member_count=Count('memberships')).order_by('pk')
    return render(request,'core/platform.html',{'platform_teams':teams})
