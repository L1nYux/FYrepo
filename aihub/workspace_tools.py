"""Local tool adapters; business rules remain in core commands and forms."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse
from core.models import Task
from core.tenancy import scope
from core import permissions as perms, document_permissions as documents
from core.workspace_commands import active_project


def target(user, name, args):
    from .agent import available
    if name == 'create_task':
        project = available(user, 'project').filter(pk=args['project_id']).first()
        obj = project
    elif name == 'update_task_progress':
        obj = available(user, 'task').select_related('project__workspace__team').filter(pk=args['task_id']).first()
        project = obj.project if obj else None
    elif name == 'save_document_draft':
        obj = documents.visible(user).filter(pk=args['document_id']).first()
        project = documents.related_project(obj) if obj else None
    else:
        raise ValidationError('没有登记这项写入工具。')
    if not obj or not project:
        raise PermissionDenied('资料不可用或无权操作。')
    with scope(project.workspace):
        active_project(project)
        if name == 'create_task':
            perms.require_project_manager(user, project)
        elif name == 'update_task_progress':
            perms.require_progress_worker(user, obj)
        elif not documents.editor(user, obj) or obj.kind != 'online':
            raise PermissionDenied('需要在线文档编辑权限。')
    return project, obj


def write_tool(user, name, args):
    from .agent import source
    from core.forms import TaskForm
    from core.workspace_commands import save_task_form, update_task_progress, save_document_text_draft
    project, obj = target(user, name, args)
    with scope(project.workspace):
        if name == 'create_task':
            parent = None
            if args.get('parent_id'):
                parent = Task.objects.filter(pk=args['parent_id'], project=project, parent__isnull=True, archived_at__isnull=True).first()
                if not parent:
                    raise ValidationError('母任务已不可用。')
            data = {'title': args['title'], 'description': args.get('description', ''),
                'assignee': args.get('assignee_id', ''), 'members': args.get('member_ids', []), 'due_date': args.get('due_date', ''),
                'category': parent.category if parent else 'other', 'competition': parent.competition_id if parent else ''}
            form = TaskForm(data, instance=Task(project=project, parent=parent, created_by=user), project=project, parent=parent, user=user)
            task = save_task_form(user, form)
            return {'saved': True, 'source': source(user, 'task', task), 'progress': task.progress}
        if name == 'update_task_progress':
            task = update_task_progress(user, obj, args['progress'], expected=args['expected_progress'])
            return {'saved': True, 'source': source(user, 'task', task), 'progress': task.progress}
        draft = save_document_text_draft(user,obj,args['draft_id'],args['generation'],args['text'])
        obj=draft.document
        ref = source(user, 'document', obj)
        ref['url'] = reverse('document_detail', args=[obj.pk]) + '?draft=' + str(draft.pk)
        return {'saved': True, 'draft_id': draft.pk, 'generation': draft.generation, 'state':'draft', 'source':ref}
