"""Business commands shared by forms and delegated Agent tools."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F
from . import permissions as perms
from .models import Project, Task, SharedDocument, DocumentDraft


def active_project(project):
    if project.archived_at or not project.workspace.active or (project.workspace.team_id and not project.workspace.team.active):
        raise ValidationError('项目或所属团队已不可用。')


def save_task_form(user, form):
    with transaction.atomic():
        project = Project.objects.select_for_update().select_related('workspace__team').get(pk=form.project.pk)
        active_project(project)
        parent = form.parent
        if not (perms.can_manage_project(user, project) or
                (not form.instance.pk and parent and project.is_participant(user))):
            raise PermissionDenied('没有创建或修改任务的权限。')
        if parent and (parent.archived_at or parent.project_id != project.pk or parent.parent_id):
            raise ValidationError('母任务已不可用或不属于当前项目。')
        if not form.is_valid():
            raise ValidationError('；'.join(str(error) for errors in form.errors.values() for error in errors))
        return form.save()


def update_task_progress(user, task, value, *, expected=None):
    from .forms import ProgressForm
    with transaction.atomic():
        Task.objects.filter(pk=task.pk).update(progress=F('progress'))
        task = Task.objects.select_for_update().select_related('project__workspace__team', 'parent').get(pk=task.pk)
        active_project(task.project)
        if task.archived_at or (task.parent_id and task.parent.archived_at):
            raise ValidationError('任务已归档。')
        perms.require_progress_worker(user, task)
        if task.status != Task.OPEN:
            raise ValidationError('任务已提交或已结项，不能直接改进度。')
        if expected is not None and task.progress != expected:
            raise ValidationError('任务进度已被其他操作更新，请重新读取后再修改。')
        form = ProgressForm({'progress': value})
        if not form.is_valid():
            raise ValidationError('进度应为 0 到 99。')
        task.progress = form.cleaned_data['progress']
        task.save(update_fields=['progress', 'updated_at'])
        return task


def save_document_draft(user, document, draft, generation, value):
    from . import document_permissions as access, document_content as content
    with transaction.atomic():
        SharedDocument.objects.filter(pk=document.pk).update(updated_at=F('updated_at'))
        document = SharedDocument.objects.select_for_update().get(pk=document.pk)
        draft = DocumentDraft.objects.select_for_update().get(pk=draft.pk, document=document)
        if document.kind != 'online' or not access.draft_editable(user, draft):
            raise PermissionDenied('修改稿已提交或编辑权限已失效。')
        if type(generation) is not int or generation != draft.generation:
            raise ValidationError('另一处已保存新的修改，请保留当前内容后重新打开。', code='conflict')
        draft.content = content.clean(value, document.pk)
        draft.generation += 1
        draft.save(update_fields=['content', 'generation', 'updated_at'])
        return draft


def save_document_text_draft(user, document, draft_id, generation, text):
    """Create or update the author's editable draft using plain text content."""
    from . import document_permissions as access
    with transaction.atomic():
        SharedDocument.objects.filter(pk=document.pk).update(updated_at=F('updated_at'))
        document=SharedDocument.objects.select_for_update().select_related('current').get(pk=document.pk)
        if document.kind!='online' or not access.editor(user,document):
            raise PermissionDenied('需要在线文档编辑权限。')
        draft=document.drafts.select_for_update().filter(author=user,state__in=['draft','submitted','changes_requested']).first()
        if draft_id==0:
            if draft or generation!=0 or not document.current:
                raise ValidationError('已有修改稿或文档版本已变化，请重新读取文档。')
            draft=DocumentDraft.objects.create(document=document,author=user,base=document.current,content=document.current.content)
        elif not draft or draft.pk!=draft_id:
            raise ValidationError('修改稿已变化，请重新读取文档。')
        # Text is editor data; markup is never evaluated.
        value={'type':'doc','content':[{'type':'paragraph',**({'content':[{'type':'text','text':line}]} if line else {})}
            for line in text.split('\n')]}
        return save_document_draft(user,document,draft,generation,value)
