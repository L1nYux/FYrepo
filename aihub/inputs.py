"""Persist steering before ACK; consume only between complete model/tool steps."""
import uuid
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F
from .models import AssistantInput, AssistantJob


def metadata(value):
    return {'id':str(value.pk), 'request_id':str(value.request_id), 'sequence':value.sequence,
        'text':value.text, 'state':value.state}


def enqueue(job, user, text, request_id):
    if not isinstance(text, str) or not text.strip() or len(text)>30000:
        raise ValidationError('补充要求应为 1–30000 个字符。')
    if not isinstance(request_id, str) or len(request_id)>36:
        raise ValidationError('补充消息标识无效。')
    try:identifier=uuid.UUID(request_id)
    except ValueError:raise ValidationError('补充消息标识无效。') from None
    from .execution import _event
    from .funding import check
    with transaction.atomic():
        if not get_user_model().objects.filter(pk=user.pk,is_active=True).update(is_active=F('is_active')):
            raise PermissionDenied('个人账号已不可用。')
        # Writer lock before reading on SQLite; no changes to the worker lease.
        locked=AssistantJob.all_objects.filter(pk=job.pk,user=user,workspace_id=job.workspace_id)
        if not locked.update(heartbeat_at=F('heartbeat_at')):
            raise PermissionDenied('本轮任务已不可用。')
        fresh=locked.select_for_update().get()
        existing=AssistantInput.all_objects.filter(job=fresh,request_id=identifier).first()
        if existing:
            if existing.text!=text.strip():raise ValidationError('相同消息标识不能用于不同内容。')
            return existing
        if (fresh.state!='running' or fresh.cancel_requested or fresh.execution.get('version')!=1
            or fresh.execution.get('phase') not in ('prepare','ready','calling','tools')):
            raise ValidationError('本轮正在收尾或已停止，请保留输入，完成后发送。')
        check(user,fresh.billing_workspace)
        rows=list(AssistantInput.all_objects.filter(job=fresh))
        if sum(row.state=='queued' for row in rows)>=20 or len(rows)>=100:
            raise ValidationError('等待处理的补充较多，请等助手处理后再发送。')
        if len((fresh.user_text+''.join(row.text for row in rows)+text).encode('utf-8'))>100000:
            raise ValidationError('本轮补充内容已达上限，请完成后新建对话。')
        value=AssistantInput(job=fresh,workspace_id=fresh.workspace_id,team_id=fresh.team_id,
            request_id=identifier,sequence=fresh.event_sequence+1,text=text.strip())
        from core.tenancy import scope
        with scope(fresh.workspace):value.save()
        _event(fresh,'input.accepted',{'input_id':str(value.pk)})
        return value


def queued(job):
    return AssistantInput.all_objects.filter(job_id=job.pk,state='queued')


def discard(job):
    """Called under the job writer lock when stopping; accepted text stays visible."""
    from .execution import _event
    identifiers=list(queued(job).values_list('pk',flat=True))
    if identifiers:
        queued(job).update(state='discarded')
        _event(job,'input.discarded',{'input_ids':[str(value) for value in identifiers]})


def retry_history(job):
    rows=[{'role':'user','content':job.user_text,'_turn':str(job.pk)}]
    rows.extend({'role':'user','content':value.text,'_turn':str(job.pk)}
        for value in AssistantInput.all_objects.filter(job=job).exclude(state='discarded'))
    return rows
