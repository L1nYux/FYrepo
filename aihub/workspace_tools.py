"""Local tool adapters; business rules remain in core commands and forms."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse
from core.models import Task
from core.tenancy import scope
from core import permissions as perms, document_permissions as documents
from core.workspace_commands import active_project


def target(user, name, args):
    from .agent import available
    if name in ('create_task','create_experiment_record'):
        project = available(user, 'project').filter(pk=args['project_id']).first()
        obj = project
    elif name == 'update_task_progress':
        obj = available(user, 'task').select_related('project__workspace__team').filter(pk=args['task_id']).first()
        project = obj.project if obj else None
    elif name == 'save_document_draft':
        obj = documents.visible(user).filter(pk=args['document_id']).first()
        project = documents.related_project(obj) if obj else None
    elif name=='update_experiment_record':
        obj=available(user,'experiment').select_related('project__workspace__team').filter(pk=args['experiment_id']).first()
        project=obj.project if obj else None
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
        elif name in ('create_experiment_record','update_experiment_record'):
            from core.workspace_commands import require_experiment_editor
            require_experiment_editor(user,obj if name=='update_experiment_record' else None,project)
            if name=='update_experiment_record' and obj.status=='archived':raise ValidationError('实验已归档。')
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
        if name in ('create_experiment_record','update_experiment_record'):
            from django.http import QueryDict
            from core.forms import ExperimentForm
            from core.models import Experiment
            from core.workspace_commands import save_experiment_form
            data=QueryDict('',mutable=True)
            item=Experiment(project=project,created_by=user) if name=='create_experiment_record' else obj
            fields=('number','title','status','content','purpose','conclusion','source_id','batch','model_name','prompt_version','procedure','result','human_review','github_url','git_ref')
            for field in fields:data[field]=args.get(field,getattr(item,field,''))
            data['project']=str(project.pk)
            data.setlist('parameter_name',[row['name'] for row in item.parameters])
            data.setlist('parameter_value',[row['value'] for row in item.parameters])
            if name=='update_experiment_record' and not set(args)&{'content','result','conclusion','status'}:raise ValidationError('请提供需要修改的实验内容。')
            form=ExperimentForm(data,instance=item,user=user);form.fields['project'].disabled=True
            entry=save_experiment_form(user,form,origin_task=item.origin_task,expected_updated_at=args.get('expected_updated_at'))
            return {'saved':True,'source':source(user,'experiment',entry),'status':entry.status,'updated_at':entry.updated_at.isoformat()}
        draft = save_document_text_draft(user,obj,args['draft_id'],args['generation'],args['text'])
        obj=draft.document
        ref = source(user, 'document', obj)
        ref['url'] = reverse('document_detail', args=[obj.pk]) + '?draft=' + str(draft.pk)
        return {'saved': True, 'draft_id': draft.pk, 'generation': draft.generation, 'state':'draft', 'source':ref}
