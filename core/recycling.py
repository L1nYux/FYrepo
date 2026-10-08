"""Permanent deletion of objects explicitly selected from the recycle bin."""
from django.apps import apps
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import Q
from django.core.exceptions import ValidationError
from .models import Attachment, Comment, ExpenseClaim, Experiment, FinanceEntry, Submission, Task, UsageReceipt


def deletion_scope(item, kind):
    """One shared definition for the preview, confirmation and actual deletion."""
    if kind == 'competition':
        return {'tasks': [], 'submissions': [], 'comments': [], 'attachments': [], 'active': []}
    if kind in ('finance', 'claim'):
        entries = [item.pk] if kind == 'finance' else ([item.entry_id] if item.entry_id else [])
        claims = list(ExpenseClaim.objects.filter(entry_id__in=entries).values_list('pk', flat=True)) if entries else [item.pk]
        files = list(Attachment.objects.filter(Q(entry_id__in=entries) | Q(claim_id__in=claims)).values_list('pk', flat=True))
        return {'tasks': [], 'submissions': [], 'comments': [], 'attachments': sorted(files), 'active': [], 'entries': sorted(entries), 'claims': sorted(claims)}
    if kind == 'project':
        task_ids = list(Task.objects.filter(project=item).values_list('pk', flat=True))
        submissions = Submission.objects.filter(Q(project=item) | Q(task_id__in=task_ids))
        comments = Comment.objects.filter(Q(project=item) | Q(task_id__in=task_ids))
    else:
        task_ids = {item.pk}
        frontier = {item.pk}
        while frontier:
            found = set(Task.objects.filter(parent_id__in=frontier).values_list('pk', flat=True)) - task_ids
            task_ids.update(found)
            frontier = found
        submissions = Submission.objects.filter(task_id__in=task_ids)
        comments = Comment.objects.filter(task_id__in=task_ids)
    submission_ids = list(submissions.values_list('pk', flat=True))
    comment_ids = list(Comment.objects.filter(Q(pk__in=comments.values('pk')) | Q(submission_id__in=submission_ids)).values_list('pk', flat=True))
    attachment_ids = list(Attachment.objects.filter(Q(submission_id__in=submission_ids) | Q(comment_id__in=comment_ids)).values_list('pk', flat=True))
    active = list(Task.objects.filter(pk__in=task_ids, archived_at__isnull=True).values_list('pk', flat=True))
    return {'tasks': sorted(task_ids), 'submissions': sorted(submission_ids), 'comments': sorted(comment_ids), 'attachments': sorted(attachment_ids), 'active': sorted(active)}


def deletion_blocker(kind, scope):
    if kind in ('finance','claim') and UsageReceipt.objects.filter(claim_id__in=scope['claims']).exists():
        return '关联申请仍被 API 用量凭证引用，当前不能永久删除。可以保留在回收站。'
    return ''


def remove_contents(item, kind, scope=None):
    """Called in a transaction after confirmation and archived state checks."""
    scope = scope if scope is not None else deletion_scope(item, kind)
    if scope['active']:
        raise ValidationError('仍有未移入回收站的任务，永久删除未执行。')
    if kind == 'competition':
        item.delete()
        return
    task_ids, submission_ids, comment_ids = scope['tasks'], scope['submissions'], scope['comments']
    filenames = set(Attachment.objects.filter(pk__in=scope['attachments']).values_list('file', flat=True))
    if kind in ('finance', 'claim'):
        reason=deletion_blocker(kind,scope)
        if reason:raise ValidationError(reason)
        if FinanceEntry.objects.filter(pk__in=scope['entries'], archived_at__isnull=True).exists() or ExpenseClaim.objects.filter(pk__in=scope['claims'], archived_at__isnull=True).exists():
            raise ValidationError('关联财务记录已恢复，请重新查看删除范围。')
        ExpenseClaim.objects.filter(pk__in=scope['claims']).delete()
        FinanceEntry.objects.filter(pk__in=scope['entries']).delete()
        def cleanup_finance_files():
            for name in filenames:
                if name and not Attachment.objects.filter(file=name).exists():
                    try: default_storage.delete(name)
                    except OSError: pass
        transaction.on_commit(cleanup_finance_files)
        return
    Submission.objects.filter(pk__in=submission_ids).delete()
    Comment.objects.filter(pk__in=comment_ids).delete()
    Task.objects.filter(pk__in=task_ids).update(parent=None)
    Task.objects.filter(pk__in=task_ids).delete()
    if kind == 'project':
        Experiment.objects.filter(project=item).update(project=None)
        FinanceEntry.objects.filter(project=item).update(project=None)
        ExpenseClaim.objects.filter(project=item).update(project=None)
        if apps.is_installed('aihub'):
            apps.get_model('aihub', 'Call').objects.filter(project=item).update(project=None)
        item.delete()

    def cleanup_files():
        for name in filenames:
            if name and not Attachment.objects.filter(file=name).exists():
                try: default_storage.delete(name)
                except OSError: pass
    transaction.on_commit(cleanup_files)
