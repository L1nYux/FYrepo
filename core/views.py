import hashlib
from pathlib import Path

from django.contrib import messages
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import FinanceForm, ProgressForm, RegisterForm, ReviewForm, SubmissionForm, TaskForm
from .models import AuditEvent, FinanceEntry, Invite, Submission, Task


def require_admin(request):
    if not request.user.is_staff:
        raise PermissionDenied


def register(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    form = RegisterForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        digest = hashlib.sha256(form.cleaned_data['invite_code'].encode()).hexdigest()
        now = timezone.now()
        try:
            with transaction.atomic():
                invite = Invite.objects.filter(code_hash=digest, used_at__isnull=True,
                                               revoked_at__isnull=True, expires_at__gt=now).first()
                if invite is None:
                    form.add_error('invite_code', '邀请码无效、已使用或已过期。')
                else:
                    user = form.save(commit=False)
                    user.is_staff = False
                    user.is_superuser = False
                    user.save()
                    changed = Invite.objects.filter(pk=invite.pk, used_at__isnull=True,
                                                    revoked_at__isnull=True, expires_at__gt=now).update(
                        used_by=user, used_at=now)
                    if changed != 1:
                        raise IntegrityError('邀请码已被使用')
                    AuditEvent.record(user, 'register', f'user:{user.pk}', invite_id=invite.pk)
                    login(request, user)
                    return redirect('dashboard')
        except IntegrityError:
            form.add_error('invite_code', '邀请码已被使用，请联系管理员。')
    return render(request, 'core/register.html', {'form': form})


@login_required
def change_password(request):
    form = PasswordChangeForm(request.user, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)
        AuditEvent.record(request.user, 'account.password_change', f'user:{user.pk}')
        messages.success(request, '密码已更新。')
        return redirect('dashboard')
    return render(request, 'core/change_password.html', {'form': form})


@login_required
def dashboard(request):
    tasks = Task.objects.filter(archived_at__isnull=True).select_related('assignee')
    return render(request, 'core/dashboard.html', {'tasks': tasks})


@login_required
def task_detail(request, pk):
    task = get_object_or_404(Task.objects.select_related('assignee', 'created_by'), pk=pk, archived_at__isnull=True)
    is_assignee = task.assignee_id == request.user.pk
    submissions = task.submissions.select_related('author', 'reviewed_by')
    if not request.user.is_staff and not is_assignee:
        submissions = submissions.filter(status=Submission.ACCEPTED)
    return render(request, 'core/task_detail.html', {
        'task': task, 'is_assignee': is_assignee, 'submissions': submissions,
        'progress_form': ProgressForm(initial={'progress': task.progress}),
        'submission_form': SubmissionForm(), 'review_form': ReviewForm(),
    })


@login_required
def task_edit(request, pk=None):
    require_admin(request)
    task = get_object_or_404(Task, pk=pk, archived_at__isnull=True) if pk else None
    before = None
    if task:
        before = {'title': task.title, 'description': task.description, 'assignee_id': task.assignee_id,
                  'due_date': task.due_date.isoformat()}
    form = TaskForm(request.POST or None, instance=task)
    if request.method == 'POST' and form.is_valid():
        item = form.save(commit=False)
        if task is None:
            item.created_by = request.user
        item.save()
        AuditEvent.record(request.user, 'task.update' if task else 'task.create', f'task:{item.pk}',
                          before=before, after={'title': item.title, 'description': item.description,
                                                'assignee_id': item.assignee_id, 'due_date': item.due_date.isoformat()})
        messages.success(request, '任务已保存。')
        return redirect('task_detail', pk=item.pk)
    return render(request, 'core/task_form.html', {'form': form, 'task': task})


@login_required
@require_POST
def task_archive(request, pk):
    require_admin(request)
    task = get_object_or_404(Task, pk=pk, archived_at__isnull=True)
    task.archived_at = timezone.now()
    task.save(update_fields=['archived_at', 'updated_at'])
    AuditEvent.record(request.user, 'task.archive', f'task:{task.pk}', title=task.title)
    messages.success(request, '任务已归档。')
    return redirect('dashboard')


@login_required
@require_POST
def task_progress(request, pk):
    task = get_object_or_404(Task, pk=pk, archived_at__isnull=True)
    if task.assignee_id != request.user.pk:
        raise PermissionDenied
    if task.status != Task.OPEN:
        raise PermissionDenied
    form = ProgressForm(request.POST)
    if form.is_valid():
        old = task.progress
        task.progress = form.cleaned_data['progress']
        task.save(update_fields=['progress', 'updated_at'])
        AuditEvent.record(request.user, 'task.progress', f'task:{task.pk}', old=old, new=task.progress)
        messages.success(request, '进度已更新。')
    else:
        messages.error(request, '进度应为 0 到 99。')
    return redirect('task_detail', pk=pk)


@login_required
@require_POST
def task_submit(request, pk):
    task = get_object_or_404(Task, pk=pk, archived_at__isnull=True)
    if task.assignee_id != request.user.pk or task.status != Task.OPEN:
        raise PermissionDenied
    form = SubmissionForm(request.POST, request.FILES)
    if form.is_valid():
        with transaction.atomic():
            task = Task.objects.select_for_update().get(pk=task.pk)
            if task.status != Task.OPEN:
                raise PermissionDenied
            submission = form.save(commit=False)
            submission.task = task
            submission.author = request.user
            submission.original_name = Path(request.FILES['attachment'].name).name[:255]
            submission.save()
            task.status = Task.SUBMITTED
            task.save(update_fields=['status', 'updated_at'])
            AuditEvent.record(request.user, 'task.submit', f'task:{task.pk}', submission_id=submission.pk,
                              filename=submission.original_name)
        messages.success(request, '成果已提交，等待管理员审核。')
    else:
        messages.error(request, '提交失败：请填写成果说明并上传不超过 20 MB 的允许格式文件。')
    return redirect('task_detail', pk=pk)


@login_required
@require_POST
def submission_review(request, pk):
    require_admin(request)
    form = ReviewForm(request.POST)
    if not form.is_valid():
        messages.error(request, '请检查审核决定和审核意见。')
        submission = get_object_or_404(Submission, pk=pk)
        return redirect('task_detail', pk=submission.task_id)
    with transaction.atomic():
        submission = get_object_or_404(Submission.objects.select_for_update().select_related('task'), pk=pk)
        task = submission.task
        if submission.status != Submission.PENDING or task.status != Task.SUBMITTED:
            raise PermissionDenied
        approved = form.cleaned_data['decision'] == 'accept'
        submission.status = Submission.ACCEPTED if approved else Submission.REJECTED
        submission.review_note = form.cleaned_data['note']
        submission.reviewed_by = request.user
        submission.reviewed_at = timezone.now()
        submission.save(update_fields=['status', 'review_note', 'reviewed_by', 'reviewed_at'])
        task.status = Task.COMPLETED if approved else Task.OPEN
        if approved:
            task.progress = 100
        task.save(update_fields=['status', 'progress', 'updated_at'])
        AuditEvent.record(request.user, 'task.approve' if approved else 'task.reject', f'task:{task.pk}',
                          submission_id=submission.pk, note=submission.review_note)
    messages.success(request, '审核结果已保存。')
    return redirect('task_detail', pk=task.pk)


@login_required
def submission_download(request, pk):
    submission = get_object_or_404(Submission.objects.select_related('task'), pk=pk)
    allowed = request.user.is_staff or submission.author_id == request.user.pk or submission.status == Submission.ACCEPTED
    if not allowed or (submission.task.archived_at and not request.user.is_staff):
        raise PermissionDenied
    try:
        return FileResponse(submission.attachment.open('rb'), as_attachment=True, filename=submission.original_name)
    except FileNotFoundError:
        raise Http404('文件不存在')


@login_required
def invites(request):
    require_admin(request)
    fresh_code = None
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'create':
            invite, fresh_code = Invite.issue(request.user)
            AuditEvent.record(request.user, 'invite.create', f'invite:{invite.pk}', expires_at=invite.expires_at.isoformat())
        elif action == 'revoke':
            invite = get_object_or_404(Invite, pk=request.POST.get('id'), used_at__isnull=True, revoked_at__isnull=True)
            invite.revoked_at = timezone.now()
            invite.save(update_fields=['revoked_at'])
            AuditEvent.record(request.user, 'invite.revoke', f'invite:{invite.pk}')
            messages.success(request, '邀请码已撤销。')
            return redirect('invites')
        else:
            raise PermissionDenied
    return render(request, 'core/invites.html', {'invites': Invite.objects.select_related('used_by')[:100], 'fresh_code': fresh_code})


@login_required
def finance_list(request):
    require_admin(request)
    entries = FinanceEntry.objects.filter(voided_at__isnull=True).select_related('created_by')[:200]
    return render(request, 'core/finance_list.html', {'entries': entries})


@login_required
def finance_edit(request, pk=None):
    require_admin(request)
    entry = get_object_or_404(FinanceEntry, pk=pk, voided_at__isnull=True) if pk else None
    before = None
    if entry:
        before = {'kind': entry.kind, 'amount': str(entry.amount), 'occurred_on': entry.occurred_on.isoformat(),
                  'memo': entry.memo, 'receipt_name': entry.receipt_name,
                  'receipt_path': entry.receipt.name}
    form = FinanceForm(request.POST or None, request.FILES or None, instance=entry)
    if request.method == 'POST' and form.is_valid():
        item = form.save(commit=False)
        if entry is None:
            item.created_by = request.user
        if request.FILES.get('receipt'):
            item.receipt_name = Path(request.FILES['receipt'].name).name[:255]
        item.save()
        AuditEvent.record(request.user, 'finance.update' if entry else 'finance.create', f'finance:{item.pk}',
                          before=before, after={'kind': item.kind, 'amount': str(item.amount),
                                                'occurred_on': item.occurred_on.isoformat(), 'memo': item.memo,
                                                'receipt_name': item.receipt_name, 'receipt_path': item.receipt.name})
        messages.success(request, '财务记录已保存。')
        return redirect('finance_list')
    return render(request, 'core/finance_form.html', {'form': form, 'entry': entry})


@login_required
@require_POST
def finance_void(request, pk):
    require_admin(request)
    entry = get_object_or_404(FinanceEntry, pk=pk, voided_at__isnull=True)
    entry.voided_at = timezone.now()
    entry.save(update_fields=['voided_at', 'updated_at'])
    AuditEvent.record(request.user, 'finance.void', f'finance:{entry.pk}', amount=str(entry.amount), memo=entry.memo)
    messages.success(request, '记录已作废，操作日志仍保留。')
    return redirect('finance_list')


@login_required
def finance_receipt(request, pk):
    require_admin(request)
    entry = get_object_or_404(FinanceEntry, pk=pk)
    if not entry.receipt:
        raise Http404('没有凭证')
    try:
        return FileResponse(entry.receipt.open('rb'), as_attachment=True, filename=entry.receipt_name or 'receipt')
    except FileNotFoundError:
        raise Http404('文件不存在')


@login_required
def audit_list(request):
    require_admin(request)
    return render(request, 'core/audit_list.html', {'events': AuditEvent.objects.select_related('actor')[:200]})
