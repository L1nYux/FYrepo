"""Explicit, bounded relay fallback. Every actual attempt uses the existing ledger."""
import uuid
from dataclasses import dataclass
from decimal import Decimal

from django.core.exceptions import ValidationError, PermissionDenied
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import Call, PoolModel, Provider, ProviderHealth
from .relay import RelayError, check_token


SAFE_FAILURES = {'dns_error', 'http_401', 'http_403', 'http_404', 'http_429'}
IGNORED_FAILURES = {'http_400', 'http_404', 'http_422', 'private_endpoint',
                    'stream_not_started', 'stream_disconnected', 'execution_checkpoint_failed','usage_pending'}
PROBE_SECONDS = 120


@dataclass
class CircuitLease:
    provider_id: int
    generation: int
    token: object = None
    closed: bool = False

    def bind(self, call):
        if self.token:
            ProviderHealth.objects.filter(provider_id=self.provider_id, generation=self.generation,
                probe_token=self.token).update(probe_call=call)

    def complete(self, call=None):
        if self.closed:
            return
        with transaction.atomic():
            Provider.objects.filter(pk=self.provider_id).update(enabled=F('enabled'))
            health = ProviderHealth.objects.select_for_update().get(provider_id=self.provider_id)
            if health.generation == self.generation and health.probe_token == self.token:
                if call is None or call.error_code in IGNORED_FAILURES:
                    if self.token:
                        health.probe_until = None
                        health.probe_token = None
                        health.probe_call = None
                elif call.status == 'success' or call.error_code == 'usage_missing':
                    health.failures = 0
                    health.cooldown_until = None
                    health.probe_until = None
                    health.probe_token = None
                    health.probe_call = None
                    health.error_code = ''
                else:
                    now = timezone.now()
                    if health.last_failed_at is None or health.last_failed_at < now-timezone.timedelta(minutes=5):
                        health.failures = 0
                    health.failures += 1
                    health.last_failed_at = now
                    health.error_code = call.error_code[:60]
                    delay = 1800 if call.error_code in ('http_401', 'http_403') else 30
                    if self.token or health.failures >= 3 or call.error_code in ('http_401', 'http_403', 'http_429'):
                        health.generation += 1
                        health.cooldown_until = now+timezone.timedelta(seconds=delay)
                        health.probe_until = None
                        health.probe_token = None
                        health.probe_call = None
                health.save()
        self.closed = True


def acquire(provider):
    """Acquire the writer lock before reading, including on SQLite."""
    with transaction.atomic():
        Provider.objects.filter(pk=provider.pk).update(enabled=F('enabled'))
        if not Provider.objects.filter(pk=provider.pk, enabled=True).exists():
            raise RelayError('调用连接已停用。', 'provider_disabled', 503)
        health = ProviderHealth.objects.get_or_create(provider=provider)[0]
        now = timezone.now()
        active_probe = health.probe_until and health.probe_until > now
        if health.probe_call_id and not active_probe:
            active_probe = Call.objects.filter(pk=health.probe_call_id, status='running',
                heartbeat_at__gt=now-timezone.timedelta(seconds=90)).exists()
        if health.cooldown_until and health.cooldown_until > now or active_probe:
            raise RelayError('调用连接暂时不可用，请稍后重试。', 'provider_cooling_down', 503)
        token = None
        if health.cooldown_until is not None:
            token = uuid.uuid4()
            health.generation += 1
            health.probe_token = token
            health.probe_until = now+timezone.timedelta(seconds=PROBE_SECONDS)
            health.probe_call = None
            health.save()
        return CircuitLease(provider.pk, health.generation, token)


def reset_health(provider):
    with transaction.atomic():
        Provider.objects.filter(pk=provider.pk).update(enabled=F('enabled'))
        health = ProviderHealth.objects.get_or_create(provider=provider)[0]
        health.generation += 1
        health.failures = 0
        health.error_code = ''
        health.last_failed_at = None
        health.cooldown_until = None
        health.probe_until = None
        health.probe_token = None
        health.probe_call = None
        health.save()


def can_fallback(call):
    return call.status == 'failed' and call.cost_cny == Decimal('0') and call.error_code in SAFE_FAILURES


class RoutePlan:
    def __init__(self, model, token, tools, limit, *, group_id=None, on_reserved=None, messages=None):
        self.primary = model
        self.token = token
        self.tools = tools
        self.limit = limit
        self.position = 0
        self.request_id = None
        self.calls = []
        self.lease = None
        self.group_id = group_id
        self.on_reserved = on_reserved
        self.messages = messages or []
        self.identifiers=[model.pk]
        if model.fallback_model_id:self.identifiers.append(model.fallback_model_id)
        if model.public_alias:
            from .channels import weighted_order
            peers=PoolModel.objects.filter(public_alias=model.public_alias,enabled=True,
                provider__enabled=True,provider__protocol=model.provider.protocol).exclude(pk__in=self.identifiers).select_related('provider')
            self.identifiers.extend(item.pk for item in weighted_order(peers,8-len(self.identifiers)))
        self.identifiers=self.identifiers[:8]

    def next_model(self):
        rejected = None
        while self.position < len(self.identifiers):
            identifier = self.identifiers[self.position]
            self.position += 1
            if identifier is None:
                break
            model = PoolModel.objects.select_related('provider').filter(pk=identifier,
                enabled=True, provider__enabled=True).first()
            if not model:
                rejected = RelayError('调用模型或备用连接已停用。', 'model_unavailable', 503)
                continue
            same_group=bool(self.primary.public_alias and model.public_alias==self.primary.public_alias)
            if model.pk != self.primary.pk and (not same_group and model.model_id != self.primary.model_id
                    or model.provider.protocol != self.primary.provider.protocol
                    or model.provider_id == self.primary.provider_id):
                rejected = RelayError('备用连接配置已变化，请负责人重新选择同名模型。', 'fallback_unavailable', 503)
                continue
            if model.pk!=self.primary.pk and any(row.get('_native') for row in self.messages):
                rejected=RelayError('当前工具历史带有原连接签名，不能切换连接。','fallback_incompatible',503)
                continue
            if any(row.get('_images') or row.get('_image_ids') or row.get('_parts') for row in self.messages):
                from .images import supports_images
                if not supports_images(model):
                    rejected=RelayError('备用连接不支持本次图片输入。','fallback_incompatible',503)
                    continue
            if model.max_output_tokens < self.limit or self.tools and not model.supports_tools:
                rejected = RelayError('备用模型不支持本次请求的输出上限或工具。', 'fallback_incompatible', 503)
                continue
            try:
                if self.token is not None:check_token(self.token, model)
                self.lease = acquire(model.provider)
                return model
            except RelayError as error:
                rejected = error
        raise rejected or RelayError('没有可用的备用连接。', 'fallback_unavailable', 503)

    def reserved(self, call):
        if self.request_id is None:
            self.request_id = str(call.pk)
        group=self.group_id or self.request_id
        Call.objects.filter(pk=call.pk).update(group_id=group)
        call.group_id = uuid.UUID(str(group))
        self.calls.append(call.pk)
        self.lease.bind(call)
        if self.on_reserved is not None:self.on_reserved(call)

    def complete(self, call=None):
        if self.lease is not None:
            self.lease.complete(call)
            self.lease = None

    def details(self, call):
        return {'request_id':self.request_id, 'call_id':str(call.pk), 'attempt_count':len(self.calls),
                'selected_model':str(call.model.provider_id)+'/'+call.model.model_id,'routed_model_id':call.model_id}


def execute_routed(user, model, messages, tools, limit, options, project, experiment, token,
        *, purpose='api', group_id=None, on_progress=None, on_reserved=None):
    from .service import execute
    plan = RoutePlan(model, token, tools, limit,group_id=group_id,on_reserved=on_reserved,messages=messages)
    original_error = None
    while True:
        try:
            selected = plan.next_model()
        except RelayError:
            if original_error is not None:
                raise original_error from None
            raise
        try:
            previous_count = len(plan.calls)
            result = execute(user, selected, messages, tools, limit, options,
                project=project, experiment=experiment, api_token=token, purpose=purpose,
                group_id=plan.group_id or plan.request_id, on_reserved=plan.reserved,on_progress=on_progress)
        except Exception as error:
            call = Call.objects.get(pk=plan.calls[-1]) if len(plan.calls) > previous_count else None
            plan.complete(call)
            if isinstance(error, RelayError) and call is not None and can_fallback(call) and plan.position < len(plan.identifiers):
                original_error = error
                continue
            if isinstance(error, RelayError) and plan.request_id:
                error.call_id = plan.request_id
            elif plan.request_id and isinstance(error, ValidationError):
                raise RelayError('备用连接未发起调用：'+' '.join(error.messages),
                    'fallback_unavailable', 503, call_id=plan.request_id) from None
            elif plan.request_id and isinstance(error, PermissionDenied):
                raise RelayError('当前账户无权继续调用备用连接。', 'permission_denied', 403,
                    call_id=plan.request_id) from None
            raise
        call = Call.objects.select_related('model').get(pk=result['call_id'])
        plan.complete(call)
        result.update(plan.details(call))
        return result


def execute_assistant(user, model, messages, tools=None, limit=None, options=None,
        purpose='assistant',group_id=None,project=None,experiment=None,on_progress=None,on_reserved=None):
    if purpose!='assistant':raise ValueError('Assistant routing requires the assistant ledger.')
    return execute_routed(user,model,messages,tools or [],min(limit or model.max_output_tokens,model.max_output_tokens),
        options or {},project,experiment,None,purpose='assistant',group_id=group_id,
        on_progress=on_progress,on_reserved=on_reserved)
