"""Permanent deletion of objects explicitly selected from the recycle bin."""
from django.apps import apps
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import Q
from .models import Attachment, Comment, ExpenseClaim, Experiment, FinanceEntry, Submission, Task


def remove_contents(item, kind):
    """Called in a transaction after permission and archived state checks."""
    if kind == 'competition':
        item.delete()
        return
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
    filenames = set(Attachment.objects.filter(Q(submission_id__in=submission_ids) | Q(comment_id__in=comment_ids)).values_list('file', flat=True))
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
