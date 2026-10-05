"""Member directory and account lifecycle; historical authors are retained."""
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
    accounts = User.objects.filter(member_profile__deleted_at__isnull=True)
    if not perms.is_admin(request):
        accounts = accounts.filter(is_active=True).exclude(member_profile__tier=MemberProfile.NORMAL)
    if query:
        accounts = accounts.filter(Q(username__icontains=query) | Q(first_name__icontains=query) |
            Q(public_profile__is_public=True, public_profile__display_name__icontains=query) |
            Q(public_profile__is_public=True, public_profile__research_area__icontains=query))
    accounts = accounts.select_related('member_profile', 'public_profile').prefetch_related('owned_projects').annotate(
        owned=Count('owned_projects', distinct=True), assigned=Count('assigned_tasks', distinct=True)
    ).order_by('-is_staff', '-is_active', 'username', 'pk')
    accounts = page(request, accounts)
    for account in accounts:
        account.role_label = perms.role_label(perms.account_role(account))
        account.tier = perms.account_role(account)
        public = getattr(account, 'public_profile', None)
        account.directory_name = (public.display_name if public and public.is_public else '') or account.first_name or account.username
        account.directory_area = public.research_area if public and public.is_public else ''
        account.directory_bio = public.bio if public and public.is_public else ''
        account.directory_projects = [p for p in account.owned_projects.all() if p.archived_at is None][:12]
    return render(request, 'core/members.html', {'accounts': accounts, 'member_query': query})


def lock_target(request, pk):
    """All admin lifecycle writes acquire a DB write lock before counting admins."""
    perms.require_admin(request)
    # SQLite serializes the write; row-lock databases also lock the admin set.
    if connection.vendor == 'sqlite':
        User.objects.filter(pk=request.user.pk).update(is_active=F('is_active'))
    list(User.objects.select_for_update().filter(is_staff=True, is_active=True).order_by('pk').values_list('pk', flat=True))
    actor = User.objects.get(pk=request.user.pk)
    if not actor.is_active or not actor.is_staff:
        raise PermissionDenied
    target = get_object_or_404(User.objects.select_for_update(of=('self',)),
                              pk=pk, member_profile__deleted_at__isnull=True)
    if target.pk == request.user.pk:
        raise PermissionDenied('不能对自己的账号执行此操作，请让另一位管理员处理。')
    return target


def last_admin(target):
    return target.is_staff and target.is_active and User.objects.filter(is_staff=True, is_active=True).count() <= 1


def invalidate_credentials(target):
    from aihub.models import MemberToken
    now = timezone.now()
    MemberToken.objects.filter(user=target, revoked_at__isnull=True).update(revoked_at=now)
    EmailVerificationCode.objects.filter(user=target, used_at__isnull=True).update(used_at=now)
    UserPresence.objects.filter(user=target).delete()


@login_required
@never_cache
@sensitive_variables('temporary')
@require_http_methods(['GET', 'POST'])
def reset_password(request, pk):
    perms.require_admin(request)
    target = get_object_or_404(User, pk=pk, member_profile__deleted_at__isnull=True)
    if target.pk == request.user.pk:
        raise PermissionDenied('请在密码与安全中修改自己的密码。')
    temporary = None
    if request.method == 'POST':
        if request.POST.get('confirm') != 'reset':
            messages.error(request, '请确认密码重置操作。')
        else:
            with transaction.atomic():
                target = lock_target(request, pk)
                temporary = secrets.token_urlsafe(18)
                target.set_password(temporary)
                target.save(update_fields=['password'])
                MemberProfile.objects.update_or_create(user=target, defaults={
                    'must_change_password': True,
                    'temporary_password_expires_at': timezone.now() + timedelta(hours=24),
                })
                invalidate_credentials(target)
    # Secret exists only in this no-store POST response, never messages/session/logs.
    response = render(request, 'core/member_reset_password.html', {'target': target, 'temporary_password': temporary})
    response['Referrer-Policy'] = 'no-referrer'
    return response


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
    target = get_object_or_404(User, pk=pk, member_profile__deleted_at__isnull=True)
    if target.pk == request.user.pk:
        raise PermissionDenied('不能删除当前账号。')
    candidates = User.objects.filter(is_active=True, member_profile__deleted_at__isnull=True).exclude(pk=pk).exclude(member_profile__tier=MemberProfile.NORMAL).order_by('username')
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
            elif pool_owner and not successor.is_staff:
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
                PublicProfile.objects.filter(user=target).update(is_public=False, display_name='', research_area='', bio='', github_url='')
                MemberProfile.objects.update_or_create(user=target, defaults={
                    'deleted_at': timezone.now(), 'avatar': '', 'must_change_password': False,
                    'temporary_password_expires_at': None,
                })
                # Keep the referenced author row; remove the usable account and personal identifiers.
                target.username = f'已删除成员-{target.pk}'
                if User.objects.exclude(pk=target.pk).filter(username=target.username).exists():
                    target.username += '-' + secrets.token_hex(4)
                target.first_name, target.last_name, target.email = '已删除成员', '', ''
                target.is_active = target.is_staff = target.is_superuser = False
                target.set_unusable_password()
                target.save(update_fields=['username', 'first_name', 'last_name', 'email', 'is_active', 'is_staff', 'is_superuser', 'password'])
                messages.success(request, f'{old_name} 的账号已删除，历史资料已保留。')
                return redirect('members')
    return render(request, 'core/member_delete.html', {
        'target': target, **responsibilities(target), 'successors': candidates,
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
