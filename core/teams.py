"""Account-level team selection and platform administration."""
import hashlib
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction, models
from django.db.models import Count, F, Q
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
    from urllib.parse import urlencode
    query={key:request.GET[key] for key in ('team','tab') if key in request.GET}
    return redirect('/messages/teams/'+('?'+urlencode(query) if query else ''))


@login_required
@require_POST
def create(request):
    from .admission import create_from_invitation, create_team
    try:
        team=create_from_invitation(request.user,request.POST.get('code'),request.POST.get('name','')) if request.POST.get('code') else create_team(request.user,request.POST.get('name',''))
    except ValidationError as error:
        messages.error(request, ' '.join(error.messages)); return redirect('teams')
    request.session['message-team']=team.pk
    request.session['workbench-team']=team.pk
    request.session['workbench-space']='team:'+str(team.pk)
    messages.success(request, '团队已创建。')
    return redirect('/messages/teams/?team='+str(team.pk))


@login_required
@require_POST
def switch(request):
    if request.POST.get('team')!='personal' and not valid_id(request.POST.get('team', '')):
        messages.error(request, '请选择有效团队。'); return redirect('teams')
    if request.POST.get('team')=='personal':
        messages.info(request,'请选择已有团队，或主动创建一个封闭团队。')
        return redirect('teams')
    membership=get_object_or_404(TeamMembership, user=request.user, team_id=request.POST.get('team'), active=True, deleted_at__isnull=True, team__active=True)
    request.session['workbench-team']=membership.team_id
    request.session['workbench-space']='team:'+str(membership.team_id)
    request.session.pop(perms.SESSION_KEY, None)
    destination=request.POST.get('next')
    if destination=='messages_teams':return redirect('messages_teams')
    if membership.role!='guest' and destination in ('team_manage','recruitment_manage'):
        return redirect(destination)
    return redirect('workspace_home' if membership.role!='guest' else 'showcase')


@login_required
@require_POST
def rename(request):
    if not perms.is_admin(request) or not request.team:
        raise PermissionDenied('仅团队所有者或管理员可修改团队名称。')
    name=request.POST.get('name','').strip()
    if not name or len(name)>100:
        messages.error(request,'团队名称须为 1–100 字。')
    else:
        Team.objects.filter(pk=request.team.pk,active=True).update(name=name)
        messages.success(request,'团队名称已更新。')
    return redirect('teams')


@login_required
@require_POST
def join(request):
    from .admission import join_from_invitation
    try:
        team=join_from_invitation(request.user, request.POST.get('code',''))
    except ValidationError as error:
        messages.error(request,' '.join(error.messages)); return redirect('teams')
    request.session['message-team']=team.pk
    return redirect('/messages/teams/?team='+str(team.pk))


@login_required
@require_POST
def transfer(request):
    if not valid_id(request.POST.get('user', '')):
        messages.error(request, '请选择接任成员。'); return redirect('teams')
    with transaction.atomic():
        Team.objects.filter(pk=getattr(request.team,'pk',None),owner=request.user,active=True).update(owner_id=F('owner_id'))
        team=get_object_or_404(Team.objects.select_for_update(),pk=getattr(request.team,'pk',None),owner=request.user,active=True)
        target=get_object_or_404(TeamMembership.objects.select_for_update(),team=team,user_id=request.POST.get('user'),active=True,role__in=['admin','member'],deleted_at__isnull=True,user__is_active=True)
        if target.user_id==request.user.pk:
            messages.error(request,'请选择另一位团队成员。'); return redirect('teams')
        if request.POST.get('confirm') != team.name:
            messages.error(request,'请填写团队名称确认交接。'); return redirect('teams')
        TeamMembership.objects.filter(team=team,role='owner').update(role='admin')
        target.role='owner';target.save(update_fields=['role'])
        team.owner=target.user;team.save(update_fields=['owner'])
        from .models import ChatGroup, GroupMember
        ChatGroup.objects.filter(team=team,is_default=True).update(owner=target.user)
        GroupMember.objects.filter(group__team=team,group__is_default=True,user=target.user).update(admin=True)
    messages.success(request,'团队所有权已交接。');return redirect('teams')


@login_required
@require_POST
def leave(request):
    from .models import GroupMember
    from .member_management import responsibilities, invalidate_credentials
    with transaction.atomic():
        team=get_object_or_404(Team.objects.select_for_update(),pk=getattr(request.team,'pk',None),active=True)
        member=get_object_or_404(TeamMembership.objects.select_for_update(),team=team,user=request.user,active=True,deleted_at__isnull=True)
        if team.owner_id==request.user.pk:
            raise PermissionDenied('请先交接所有权或解散团队。')
        from aihub.models import PoolSettings
        if PoolSettings.objects.filter(owner=request.user).exists() or any(rows.exists() for rows in responsibilities(request.user).values()):
            messages.error(request,'请先请团队管理员交接你负责的项目、任务、比赛或 API 池。')
            return redirect('teams')
        member.active=False;member.deleted_at=timezone.now();member.permissions=[];member.save()
        GroupMember.objects.filter(group__team=team,user=request.user).update(active=False)
        invalidate_credentials(request.user)
    request.session['workbench-space']='personal';request.session.pop('workbench-team',None);request.session.pop('message-team',None)
    messages.success(request,'已退出团队。好友和私信记录保留，可切换到其他团队或创建、加入团队。')
    return redirect('messages_teams')


@login_required
@require_POST
def disband(request):
    from .models import Workspace, ChatGroup, GroupMember, TeamOpening
    from aihub.models import MemberToken, AssistantJob
    with transaction.atomic():
        team=get_object_or_404(Team.objects.select_for_update(),pk=getattr(request.team,'pk',None),owner=request.user,active=True)
        if request.POST.get('confirm')!=team.name:
            messages.error(request,'请输入团队名称确认解散。');return redirect('teams')
        if AssistantJob.all_objects.filter(state='running', heartbeat_at__gt=timezone.now()-timezone.timedelta(minutes=20)).filter(Q(team=team)|Q(billing_workspace__team=team)).exists():
            messages.error(request,'团队仍有 AI 调用正在运行，请等待完成或先停止调用，再解散团队。');return redirect('teams')
        team.active=False;team.listed=False;team.disbanded_at=timezone.now();team.save(update_fields=['active','listed','disbanded_at'])
        TeamMembership.objects.filter(team=team).update(active=False,deleted_at=timezone.now())
        # Converted solo workspaces used to keep the account's one-to-one
        # storage owner. Release that slot while retaining every team record.
        old_space=Workspace.objects.filter(team=team).first()
        Workspace.objects.filter(team=team).update(active=False, owner=None)
        if old_space and old_space.owner_id==request.user.pk:
            from .solo_teams import account_storage
            from .models import Sticker
            from aihub.models import AssistantConversation, AssistantJob, AssistantJobOrder, AssistantImage
            private=account_storage(request.user)
            # Only private history moves. Billing ownership and team ledgers
            # remain in their original archived workspace.
            for model in (AssistantConversation,AssistantJob,AssistantImage):
                model._base_manager.filter(workspace=old_space,user=request.user).update(workspace=private,team=None)
            AssistantJobOrder._base_manager.filter(workspace=old_space,job__user=request.user).update(workspace=private,team=None)
            Sticker._base_manager.filter(workspace=old_space,created_by=request.user).update(workspace=private,team=None)
        TeamOpening.objects.filter(team=team).update(active=False)
        ChatGroup.objects.filter(team=team).update(active=False)
        GroupMember.objects.filter(group__team=team).update(active=False)
        MemberToken.all_objects.filter(team=team,revoked_at__isnull=True).update(revoked_at=timezone.now())
        from .models import Invite
        Invite.all_objects.filter(team=team,used_at__isnull=True,revoked_at__isnull=True).update(revoked_at=timezone.now())
    request.session['workbench-space']='personal';request.session.pop('workbench-team',None);request.session.pop('message-team',None)
    messages.success(request,'团队已解散，历史业务记录保留。')
    return redirect('messages_teams')


@login_required
def platform(request):
    from .team_permissions import can_manage_admission
    from .models import TeamCreationInvite
    from .pagination import page
    if not can_manage_admission(request):
        from .account_lifecycle import can_manage
        if request.method=='GET' and can_manage(request):return redirect('platform_accounts')
        raise PermissionDenied('未获得软件管理权限。')
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
                if target.disbanded_at:raise PermissionDenied('已解散团队不能恢复或修改规模。')
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
    position=request.POST.get('position','').strip()
    capabilities=set(request.POST.getlist('permissions'))
    if len(position)>60 or set(capabilities)-{key for key,_label in CAPABILITIES}:
        raise PermissionDenied('职务或权限设置无效。')
    with transaction.atomic():
        team=get_object_or_404(Team.objects.select_for_update(),pk=getattr(request.team,'pk',None),active=True)
        actor=TeamMembership.objects.select_for_update().filter(team=team,user=request.user,active=True,
            deleted_at__isnull=True,role__in=['owner','admin']).first()
        if not actor:
            raise PermissionDenied('需要本团队的管理权限。')
        member=get_object_or_404(TeamMembership.objects.select_for_update(),pk=pk,team=team,deleted_at__isnull=True)
        owner=actor.role=='owner' and team.owner_id==request.user.pk
        if not owner and member.role=='owner':
            raise PermissionDenied('只有团队所有者可以修改所有者资料。')
        if not owner and ('recruitment' in capabilities)!=('recruitment' in member.permissions):
            raise PermissionDenied('只有团队所有者可以授予或撤销 HR 权限。')
        TeamMembership.objects.filter(pk=member.pk,team=team).update(position=position,permissions=sorted(capabilities))
    messages.success(request,'成员在本团队的职务与授权已保存。')
    return redirect('team_manage')
