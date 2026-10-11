"""Database queue and fenced checkpoints for private assistant turns.

A checkpoint is committed before a paid request and before dispatching tools.
An interrupted request with no saved response is never automatically resent.
Local writes have their own transactional receipts in delegation.py.
"""
import logging
import json
import threading
import uuid
from contextlib import contextmanager
from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connections, OperationalError, transaction
from django.db.models import F, Q
from django.utils import timezone
from .models import AssistantEvent, AssistantJob, Call

LEASE_SECONDS = 120
RESUMABLE = {'prepare', 'ready', 'tools', 'finalizing'}
logger = logging.getLogger(__name__)


class LeaseLost(Exception):
    pass


class InputsPending(Exception):
    pass


def pending_usage(job):
    return Call.all_objects.filter(group_id=job.pk, user_id=job.user_id, status__in=['running', 'unknown']).exists()


def usage(job):
    rows = list(Call.all_objects.filter(group_id=job.pk, user_id=job.user_id,
        workspace_id=job.billing_workspace_id))
    return {'calls':len(rows), 'cost_cny':str(sum((row.cost_cny or Decimal(0) for row in rows), Decimal(0))),
        'tokens':sum((row.input_tokens or 0)+(row.output_tokens or 0) for row in rows),
        'pending_cost':any(row.status in ('running', 'unknown') for row in rows)}


def can_continue(job):
    return (job.state == 'error' and not job.cancel_requested and job.execution.get('version') == 1
        and job.execution.get('phase') in RESUMABLE and not pending_usage(job))


def can_retry(job):
    return job.state == 'error' and not pending_usage(job)


def _event(job, kind, payload):
    # Called only after acquiring the SQLite writer lock / row lock.
    from core.tenancy import scope
    job.event_sequence += 1
    with scope(job.workspace):
        AssistantEvent.all_objects.create(job=job, workspace_id=job.workspace_id, team_id=job.team_id,
            sequence=job.event_sequence, kind=kind, payload=payload or {})
    AssistantJob.all_objects.filter(pk=job.pk).update(event_sequence=job.event_sequence)


class Journal:
    def __init__(self, job, token):
        self.job = job
        self.token = token
        self.data = dict(job.execution)

    def owned(self):
        return AssistantJob.all_objects.filter(pk=self.job.pk, state='running', lease_token=self.token,
            lease_expires_at__gt=timezone.now())

    def check(self):
        if not self.owned().exists():
            raise LeaseLost()

    def save(self, kind, payload=None, **changes):
        data = {**self.data, **changes}
        with transaction.atomic():
            if not self.owned().update(heartbeat_at=timezone.now()):
                raise LeaseLost()
            fresh = self.owned().select_for_update().get()
            if changes.get('phase')=='finalizing':
                from .inputs import queued
                if queued(fresh).exists():raise InputsPending()
            _event(fresh, kind, payload)
            AssistantJob.all_objects.filter(pk=fresh.pk, lease_token=self.token).update(execution=data)
        self.data = data

    def apply_inputs(self, messages):
        """Input state and its context projection are committed together."""
        from .inputs import queued
        with transaction.atomic():
            if not self.owned().update(heartbeat_at=timezone.now()):raise LeaseLost()
            fresh=self.owned().select_for_update().get()
            if fresh.cancel_requested:return []
            values=list(queued(fresh).order_by('sequence'))
            if not values:return []
            projected=list(messages)+[{'role':'user','content':value.text,'_turn':str(fresh.pk)} for value in values]
            for value in values:
                queued(fresh).filter(pk=value.pk).update(state='applied',applied_at=timezone.now())
                _event(fresh,'input.applied',{'input_id':str(value.pk)})
            data={**self.data,'messages':projected,'phase':'ready','pending':None,'answer':'',
                'repair_used':False,'format_repair_used':False}
            AssistantJob.all_objects.filter(pk=fresh.pk,lease_token=self.token).update(execution=data)
        messages[:]=projected
        self.data=data
        return values

    def finish(self, state, result):
        with transaction.atomic():
            if not self.owned().update(heartbeat_at=timezone.now()):
                raise LeaseLost()
            fresh = self.owned().select_for_update().get()
            result = {**result, **usage(fresh)}
            if state=='cancelled':
                from .inputs import discard
                discard(fresh)
            _event(fresh, 'turn.'+state, {'state':state})
            data = dict(self.data)
            if state in ('done', 'cancelled'):
                # Completed jobs retain their own turn, not repeated copies of
                # every earlier turn. Large image data stays in AssistantImage.
                messages=data.get('messages',[])
                current=[index for index,row in enumerate(messages) if row.get('role')=='user' and row.get('_turn')==str(fresh.pk)]
                start=current[0] if current else max((index for index,row in enumerate(messages) if row.get('role')=='user'),default=0)
                turn=[dict(row) for row in messages[start:] if row.get('role') in ('user','assistant','tool')]
                for row in turn:row.pop('_images',None)
                if state=='cancelled' and turn:
                    returned={row.get('tool_call_id') for row in turn if row.get('role')=='tool'}
                    for call in [call for row in turn for call in row.get('tool_calls',[]) if call['id'] not in returned]:
                        turn.append({'role':'tool','tool_call_id':call['id'],'content':json.dumps({'error':'用户已停止，这项操作没有执行。','cancelled':True},ensure_ascii=False)})
                    if turn[-1].get('role')!='assistant' or turn[-1].get('tool_calls'):
                        turn.append({'role':'assistant','content':result.get('text') or '已停止。'})
                data={'version':1,'phase':'finished','model_id':data.get('model_id'),
                    'messages':turn,'step':data.get('step',0)}
            AssistantJob.all_objects.filter(pk=fresh.pk, lease_token=self.token).update(state=state,
                execution=data, result=result, finished_at=timezone.now(), lease_token=None, lease_expires_at=None)
        self.data = data


def claim(job_id):
    token = uuid.uuid4()
    now = timezone.now()
    with transaction.atomic():
        eligible = AssistantJob.all_objects.filter(pk=job_id, state='running').filter(
            Q(lease_expires_at__isnull=True) | Q(lease_expires_at__lte=now))
        if not eligible.update(lease_token=token, lease_expires_at=now+timezone.timedelta(seconds=LEASE_SECONDS), heartbeat_at=now):
            return None
        job = AssistantJob.all_objects.select_for_update().get(pk=job_id)
        journal = Journal(job, token)
        if job.execution.get('version') != 1:
            journal.finish('error', {'error':'这轮任务缺少可恢复记录，请重新提问。'})
            return None
        if (job.execution.get('phase') not in RESUMABLE|{'calling'}
            or type(job.execution.get('model_id')) is not int
            or not isinstance(job.execution.get('input_history'),list) or not job.execution['input_history']):
            journal.finish('error', {'error':'任务记录不完整，请重新提问。'})
            return None
        restored={'progress':job.result.get('progress',{}),'sources':job.execution.get('sources',[]),
            'activity':job.execution.get('activities',[])}
        if job.cancel_requested:
            journal.finish('cancelled',{**restored,'text':'已停止，已完成的操作保留。'})
            return None
        if job.execution.get('phase') == 'calling':
            # The request may have reached its provider. Even a settled bill
            # cannot reconstruct an unsaved response or its requested tools.
            journal.finish('error', {**restored,'error':'连接中断，上一请求的回复未完整保存；已完成的操作保留，请先核对用量。'})
            return None
        _event(job, 'turn.started', {'resumed':job.execution.get('phase') != 'prepare'})
        return journal


@contextmanager
def keep_alive(journal):
    stopped = threading.Event()
    def heartbeat():
        try:
            while not stopped.wait(20):
                close_old_connections()
                try:
                    if not journal.owned().update(heartbeat_at=timezone.now(),
                        lease_expires_at=timezone.now()+timezone.timedelta(seconds=LEASE_SECONDS)):
                        break
                except OperationalError:
                    logger.debug('Assistant lease heartbeat delayed', exc_info=True)
        finally:
            connections.close_all()
    thread = threading.Thread(target=heartbeat, name='assistant-lease', daemon=True)
    thread.start()
    try:
        yield
    finally:
        stopped.set()
        thread.join(timeout=2)


def continue_job(job, user, authorization=None):
    """Continue the same saved turn, without creating another user message."""
    from django.contrib.auth import get_user_model
    from .delegation import validate_grant
    from .funding import check
    from .models import PoolModel
    with transaction.atomic():
        get_user_model().objects.filter(pk=user.pk).update(is_active=F('is_active'))
        fresh = AssistantJob.all_objects.select_for_update().get(pk=job.pk, user=user, workspace_id=job.workspace_id)
        if fresh.state == 'running':
            return fresh  # Idempotent response to a repeated click / lost ACK.
        if not can_continue(fresh):
            raise ValidationError('这轮任务不能直接继续；请核对用量后重新提问。')
        if AssistantJob.all_objects.filter(user=user, state='running').exclude(pk=fresh.pk).exists():
            raise ValidationError('请先完成或停止正在执行的任务。')
        grant=fresh.authorization
        if fresh.execution['phase']!='finalizing':
            check(user, fresh.billing_workspace)
            if not PoolModel.all_objects.filter(pk=fresh.execution.get('model_id'), workspace=fresh.billing_workspace,
                enabled=True, provider__enabled=True).exists():
                raise ValidationError('原模型已停用，请重新提问并选择可用模型。')
            grant = validate_grant(user, authorization or fresh.authorization_id) if authorization or fresh.authorization_id else None
            if grant and (not fresh.authorization_id or grant.project_id != fresh.authorization.project_id):
                raise ValidationError('继续任务需沿用同一项目的授权。')
        data = {**fresh.execution, 'window_steps':0}
        _event(fresh, 'turn.continued', {})
        AssistantJob.all_objects.filter(pk=fresh.pk).update(state='running', cancel_requested=False,
            authorization=grant, execution=data, heartbeat_at=timezone.now(), finished_at=None,
            lease_token=None, lease_expires_at=None)
        fresh.state = 'running'
        return fresh


def queued():
    return AssistantJob.all_objects.filter(state='running', execution__version=1).filter(
        Q(lease_expires_at__isnull=True) | Q(lease_expires_at__lte=timezone.now())).order_by('created_at', 'creation_order__pk')


def kick(job_id=None):
    """Small local installations use two threads; production uses assistant_worker."""
    if getattr(settings, 'WORKBENCH_ASSISTANT_WORKER', 'inline') != 'inline':
        return
    from .agent import CAPACITY, worker
    if job_id is not None and not queued().filter(pk=job_id).exists():return
    identifiers = [job_id] if job_id else list(queued().values_list('pk', flat=True)[:2])
    for identifier in identifiers:
        if not CAPACITY.acquire(blocking=False):
            break
        def run(selected=identifier):
            try:
                worker(selected)
            except Exception:
                logger.exception('Assistant worker interrupted job=%s', selected)
            finally:
                connections.close_all()
                CAPACITY.release()
        try:
            threading.Thread(target=run, name='assistant-local', daemon=True).start()
        except Exception:
            CAPACITY.release()
            logger.exception('Unable to start local assistant worker')


def start_local_worker():
    def loop():
        while True:
            close_old_connections()
            try:
                kick()
            except Exception:
                logger.exception('Unable to poll local assistant queue')
            finally:
                connections.close_all()
            threading.Event().wait(2)
    threading.Thread(target=loop, name='assistant-queue', daemon=True).start()
