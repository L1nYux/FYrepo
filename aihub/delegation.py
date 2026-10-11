"""Server-side delegation and atomic receipts for local database commands."""
import hashlib
import json
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from core.tenancy import scope
from core.workspace_audit import acting_as
from .models import AgentGrant, AgentOperation, AgentPluginSetting, AssistantJob
from .tool_registry import registry, validate


def plugin_enabled(user, plugin_id):
    plugin = registry.plugins[plugin_id]
    setting = AgentPluginSetting.objects.filter(user=user, plugin=plugin_id).first()
    return setting.enabled if setting else plugin.default_enabled


def validate_grant(user, identifier):
    grant = AgentGrant.objects.select_related('project__workspace__team').filter(pk=identifier, user=user).first()
    if not grant or grant.revoked_at or grant.expires_at <= timezone.now():
        raise PermissionDenied('执行授权已过期、已撤销或不属于当前账户。')
    from .agent import available
    if not available(user, 'project').filter(pk=grant.project_id).exists():
        raise PermissionDenied('项目访问权限已失效。')
    return grant


def permitted_actions(user, project):
    from .agent import available
    from core import permissions as perms, document_permissions as docs
    from core.workspace_commands import active_project
    actions = []
    with scope(project.workspace):
        active_project(project)
        if perms.can_manage_project(user, project):
            actions.append('create_task')
        from django.db.models import Q
        tasks=available(user,'task').filter(project=project)
        can_progress=(perms.is_admin(user) or project.owner_id==user.pk or project.is_participant(user))
        if can_progress and (tasks.exists() if perms.is_admin(user) or project.owner_id==user.pk else tasks.filter(Q(assignee=user)|Q(members=user)).exists()):
            actions.append('update_task_progress')
        rows = docs.visible(user).filter(kind='online').filter(Q(project=project)|Q(task__project=project)|Q(experiment__project=project))
        if any(docs.editor(user, document) for document in rows):
            actions.append('save_document_draft')
    return [name for name in actions if plugin_enabled(user, registry.owners[name])]


def issue(user, project_id, actions, *, hours=1, max_operations=20):
    from .agent import available
    if type(project_id) is not int or project_id<=0:raise ValidationError('项目编号无效。')
    project = available(user, 'project').filter(pk=project_id).first()
    if not project:
        raise PermissionDenied('没有项目访问权限。')
    if not isinstance(actions, list) or not actions or any(not isinstance(name, str) for name in actions):
        raise ValidationError('请至少选择一种操作。')
    if set(actions) - set(permitted_actions(user, project)):
        raise PermissionDenied('不能授予当前账户没有的权限，或对应插件已关闭。')
    if type(hours) is not int or not 1 <= hours <= 8 or type(max_operations) is not int or not 1 <= max_operations <= 30:
        raise ValidationError('授权时长应为 1 到 8 小时，操作上限应为 1 到 30 次。')
    return AgentGrant.objects.create(user=user, project=project, actions=sorted(set(actions)),
        expires_at=timezone.now()+timezone.timedelta(hours=hours), max_operations=max_operations)


def definitions(user, grant=None, *, web=True):
    return [tool.definition() for name, tool in registry.tools.items()
        if plugin_enabled(user, registry.owners[name]) and (web or registry.owners[name] != 'web')
        and (tool.effect == 'read' or grant and name in grant.actions and grant.used_operations<grant.max_operations)]


def execute_operation(user, job, name, args):
    from .workspace_tools import target
    tool = registry.get(name)
    validate(tool.definition()['function']['parameters'], args)
    key = hashlib.sha256(json.dumps([name, args], ensure_ascii=False, sort_keys=True, separators=(',',':')).encode()).hexdigest()
    with transaction.atomic(), acting_as(user):
        # Acquire the writer lock before any read-to-write upgrade on SQLite.
        # Both execution and revocation lock the grant before the job.
        if not job.authorization_id:
            raise PermissionDenied('本轮没有执行授权。')
        AgentGrant.objects.filter(pk=job.authorization_id,user=user).update(used_operations=F('used_operations'))
        locked = AssistantJob.all_objects.filter(pk=job.pk, user=user, authorization_id=job.authorization_id,state='running', cancel_requested=False)
        if job.execution.get('version')==1:
            if not job.lease_token:raise ValidationError('任务执行权已失效，未继续操作。')
            locked=locked.filter(lease_token=job.lease_token,lease_expires_at__gt=timezone.now())
        if not locked.update(heartbeat_at=F('heartbeat_at')):
            raise ValidationError('任务已停止，未继续执行。')
        fresh = locked.select_for_update().get()
        from .inputs import queued
        if queued(fresh).exists():
            raise ValidationError('已收到补充要求，本次未开始操作；请结合新要求重新决定。')
        if not fresh.authorization_id:
            raise PermissionDenied('本轮没有执行授权。')
        grant = validate_grant(user, fresh.authorization_id)
        if tool.effect != 'write' or name not in grant.actions or not plugin_enabled(user, registry.owners[name]):
            raise PermissionDenied('这项操作未授权或插件已关闭。')
        project, _ = target(user, name, args)  # Recheck live business rights even on receipt replay.
        if project.pk != grant.project_id:
            raise PermissionDenied('这项资料不属于授权项目。')
        receipt = AgentOperation.objects.filter(group=fresh.operation_group, key=key, user=user, project=project).first()
        if receipt:
            return {**receipt.result, 'replayed':True, 'receipt':receipt.pk}
        if grant.used_operations >= grant.max_operations:
            raise PermissionDenied('已达到本次授权的操作上限。')
        with scope(project.workspace):
            result = registry.invoke(user, name, args)
        if not isinstance(result, dict) or not result.get('saved') or result.get('error'):
            raise ValidationError('操作没有产生有效回执，已回滚。')
        receipt = AgentOperation.objects.create(group=fresh.operation_group, key=key, user=user, project=project,
            grant=grant, tool=name, result=result)
        AgentGrant.objects.filter(pk=grant.pk).update(used_operations=F('used_operations')+1)
        return {**result, 'receipt':receipt.pk}
