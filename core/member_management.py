"""Member directory and team membership lifecycle; historical authors are retained."""
from .tenancy import team_users, required_team_id
from .identity import nickname
from .models import TeamMembership
import secrets
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.db import connection, transaction
from django.db.models import Count, F, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_http_methods

from . import permissions as perms
from .models import (Competition, EmailVerificationCode, Invite, MemberProfile,
                     Project, PublicProfile, Task, UserPresence)
from .pagination import page


def directory(request):
    if not perms.is_team_member(request):
        raise PermissionDenied
    query = request.GET.get('q', '').strip()[:160]
    accounts = team_users(include_inactive=True).filter(member_profile__deleted_at__isnull=True)
    if not perms.is_admin(request):
        accounts = accounts.filter(pk__in=team_users(member_only=True).values('pk'))
    if query:
        accounts = accounts.filter(Q(username__icontains=query) | Q(first_name__icontains=query) |
            Q(member_profile__nickname__icontains=query) | Q(member_profile__workbench_id__icontains=query) |
            Q(public_profile__is_public=True, public_profile__display_name__icontains=query) |
            Q(public_profile__is_public=True, public_profile__research_area__icontains=query))
    accounts = accounts.select_related('member_profile', 'public_profile').prefetch_related('owned_projects').annotate(
        owned=Count('owned_projects', filter=Q(owned_projects__team_id=required_team_id()), distinct=True), assigned=Count('assigned_tasks', filter=Q(assigned_tasks__team_id=required_team_id()), distinct=True)
    ).order_by('-is_staff', '-is_active', 'username', 'pk')
    accounts = page(request, accounts)
    for account in accounts:
        account.team_admin = perms.is_admin(account)
        account.team_active = TeamMembership.objects.get(team_id=required_team_id(),user=account).active
        membership=TeamMembership.objects.get(team_id=required_team_id(),user=account)
        account.role_label = membership.get_role_display()
        account.team_position=membership.position
        account.tier = perms.account_role(account)
        public = getattr(account, 'public_profile', None)
        account.directory_name = (public.display_name if public and public.is_public else '') or account.first_name or nickname(account)
        account.directory_area = public.research_area if public and public.is_public else ''
        account.directory_bio = public.bio if public and public.is_public else ''
        account.directory_projects = [p for p in account.owned_projects.all() if p.archived_at is None][:12]
    return render(request, 'core/members.html', {'accounts': accounts, 'member_query': query})


def lock_target(request, pk):
    perms.require_admin(request)
    members=TeamMembership.objects.filter(team_id=required_team_id(),deleted_at__isnull=True)
    members.filter(user=request.user).update(active=F('active'))
    list(members.select_for_update().filter(role__in=['owner','admin'],active=True).values_list('pk',flat=True))
    if not members.filter(user=request.user,role__in=['owner','admin'],active=True).exists():raise PermissionDenied
    target=get_object_or_404(team_users(include_inactive=True).select_for_update(of=('self',)),pk=pk,member_profile__deleted_at__isnull=True)
    if target.pk==request.user.pk:raise PermissionDenied('不能对自己的账号执行此操作。')
    if members.filter(user=target,role='owner').exists():raise PermissionDenied('请先交接团队所有权。')
    return target


def last_admin(target):
    members=TeamMembership.objects.filter(team_id=required_team_id(),deleted_at__isnull=True,active=True,role__in=['owner','admin'])
    return members.filter(user=target).exists() and members.count()<=1


def invalidate_credentials(target):
    from aihub.models import MemberToken
    now = timezone.now()
    MemberToken.objects.filter(user=target, revoked_at__isnull=True).update(revoked_at=now)
    # Team removal does not invalidate the account's email recovery in other teams.
    UserPresence.objects.filter(user=target).delete()


@login_required
@never_cache
@sensitive_variables('temporary')
@require_http_methods(['GET', 'POST'])
def reset_password(request, pk):
    from .account_lifecycle import reset_password as platform_reset_password
    return platform_reset_password(request, pk)


def responsibilities(target):
    return {
        'projects': Project.objects.filter(owner=target, archived_at__isnull=True),
        'tasks': Task.objects.filter(assignee=target, archived_at__isnull=True, project__archived_at__isnull=True),
        'competitions': Competition.objects.filter(owner=target, archived_at__isnull=True),
    }


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def delete_account(request, pk):
    from aihub.models import PoolSettings
    perms.require_admin(request)
    target = get_object_or_404(team_users(include_inactive=True), pk=pk, member_profile__deleted_at__isnull=True)
    if target.pk == request.user.pk:
        raise PermissionDenied('不能删除当前账号。')
    candidates = team_users(member_only=True).exclude(pk=pk).order_by('username')
    error = ''
    if request.method == 'POST':
        with transaction.atomic():
            target = lock_target(request, pk)
            related = responsibilities(target)
            pool_owner = PoolSettings.objects.filter(owner=target).exists()
            needed = pool_owner or any(rows.exists() for rows in related.values())
            successor = candidates.select_for_update(of=('self',)).filter(pk=request.POST.get('successor')).first() if request.POST.get('successor', '').isdigit() else None
            if request.POST.get('confirm_username') != target.username:
                error = '请准确输入要删除的账户名。'
            elif last_admin(target):
                error = '至少保留一名在用管理员。'
            elif needed and successor is None:
                error = '该成员仍有负责事项，请选择接任成员。'
            elif pool_owner and not perms.is_admin(successor):
                error = 'API 池负责人必须交接给一位在用管理员。'
            else:
                old_name = target.username
                if successor:
                    task_projects = list(related['tasks'].values_list('project_id', flat=True).distinct())
                    related['projects'].update(owner=successor)
                    related['tasks'].update(assignee=successor)
                    related['competitions'].update(owner=successor)
                    for project in Project.objects.filter(pk__in=task_projects):
                        project.members.add(successor)
                    if pool_owner:
                        PoolSettings.objects.filter(owner=target).update(owner=successor)
                for project in target.projects.filter(archived_at__isnull=True):
                    project.members.remove(target)
                for task in target.collaborative_tasks.filter(archived_at__isnull=True):
                    task.members.remove(target)
                invalidate_credentials(target)
                Invite.objects.filter(created_by=target, used_at__isnull=True, revoked_at__isnull=True).update(revoked_at=timezone.now())
                TeamMembership.objects.filter(team_id=required_team_id(),user=target).update(active=False,deleted_at=timezone.now(),permissions=[],position='',role='member')
                from .models import GroupMember
                GroupMember.objects.filter(group__team_id=required_team_id(),user=target).update(active=False,admin=False)
                messages.success(request,f'{target.username} 已移出本团队，历史记录和其他团队的账号权限保留。')
                return redirect('members')
    return render(request, 'core/member_delete.html', {
        'target': target, **responsibilities(target), 'successors': [account for account in candidates if not PoolSettings.objects.filter(owner=target).exists() or perms.is_admin(account)],
        'pool_owner': PoolSettings.objects.filter(owner=target).exists(), 'delete_error': error,
    })


@login_required
@never_cache
@sensitive_post_parameters('new_password1', 'new_password2')
@require_http_methods(['GET', 'POST'])
def set_password(request):
    profile = getattr(request.user, 'member_profile', None)
    if not profile or not profile.must_change_password:
        return redirect(perms.home_url_name(perms.account_role(request.user)))
    form = SetPasswordForm(request.user, request.POST if request.method == 'POST' else None)
    valid = request.method == 'POST' and form.is_valid()
    if valid and request.user.check_password(form.cleaned_data['new_password1']):
        form.add_error('new_password1', '请设置与临时密码不同的新密码。')
        valid = False
    if valid:
        with transaction.atomic():
            account = User.objects.select_for_update().get(pk=request.user.pk)
            state = MemberProfile.objects.select_for_update().get(user=account)
            if (not account.is_active or account.password != request.user.password or not state.must_change_password
                    or state.temporary_password_expires_at and state.temporary_password_expires_at <= timezone.now()):
                logout(request)
                return redirect('login')
            # Save only the password on the locked row, never stale identity fields.
            account.password = form.save(commit=False).password
            account.save(update_fields=['password'])
            form.user = account
            state.must_change_password = False
            state.temporary_password_expires_at = None
            state.save(update_fields=['must_change_password', 'temporary_password_expires_at'])
            update_session_auth_hash(request, form.user)
        messages.success(request, '新密码已设置，可以继续使用工作台。')
        return redirect(perms.home_url_name(perms.account_role(request.user)))
    return render(request, 'core/required_password_change.html', {'form': form})
