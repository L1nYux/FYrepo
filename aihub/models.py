from django.utils import timezone
from core.tenancy import TeamScopedModel
import uuid
from decimal import Decimal
from django.conf import settings
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator

NONNEGATIVE = [MinValueValidator(Decimal('0'))]


class Provider(TeamScopedModel):
    name = models.CharField('厂商名称', max_length=80)
    protocol = models.CharField('接口格式', max_length=20, default='openai', choices=[
        ('openai', 'OpenAI 兼容'), ('anthropic', 'Anthropic Messages'), ('gemini', 'Gemini 原生')])
    base_url = models.URLField('API 基础地址')
    key_env = models.CharField('密钥环境变量（可选）', max_length=120, blank=True)
    enabled = models.BooleanField('启用', default=True)
    quota_kind = models.CharField('额度类型', max_length=12, default='auto', choices=[('auto','自动识别'),('plan','订阅套餐'),('account','按量账户余额')])
    quota_snapshot = models.JSONField(default=dict, editable=False)

    def __str__(self): return self.name

    class Meta:
        constraints = [models.UniqueConstraint(fields=['workspace','name'], name='team_provider_name')]



class PoolModel(TeamScopedModel):
    provider = models.ForeignKey(Provider, on_delete=models.PROTECT, related_name='models')
    model_id = models.CharField('模型 ID', max_length=160)
    label = models.CharField('显示名称（可选）', max_length=100, blank=True)
    enabled = models.BooleanField('启用', default=True)
    supports_tools = models.BooleanField('支持助手工具调用', default=True)
    supports_images = models.BooleanField('支持图片输入（留空自动识别）', null=True, blank=True, default=None)
    output_parameter = models.CharField('输出上限参数', max_length=24, default='max_tokens',
        choices=[('max_tokens','max_tokens'),('max_completion_tokens','max_completion_tokens')])
    max_output_tokens = models.PositiveIntegerField('最大输出 token', default=32768,
        validators=[MinValueValidator(64), MaxValueValidator(32768)])
    price_feed_url = models.URLField('每日价格 JSON 地址（可选）', blank=True)
    price_source = models.URLField('价格依据网址（可选）', blank=True)
    price_mode = models.CharField('价格更新', max_length=8, default='auto', choices=[('auto','自动同步公开价格'),('manual','使用自定义价格')])
    fallback_model = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='primary_models', verbose_name='备用连接（可选）')

    class Meta:
        constraints = [models.UniqueConstraint(fields=['provider', 'model_id'], name='pool_unique_provider_model')]

    def __str__(self):
        from .discovery import model_label
        return model_label(self.model_id,self.label or self.model_id)


class ProviderHealth(TeamScopedModel):
    """Shared circuit state; a fenced, expiring lease permits one recovery probe."""
    provider = models.OneToOneField(Provider, on_delete=models.CASCADE, related_name='relay_health')
    failures = models.PositiveIntegerField(default=0)
    last_failed_at = models.DateTimeField(null=True, blank=True)
    cooldown_until = models.DateTimeField(null=True, blank=True)
    probe_until = models.DateTimeField(null=True, blank=True)
    probe_token = models.UUIDField(null=True, blank=True)
    probe_call = models.ForeignKey('Call', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    generation = models.PositiveBigIntegerField(default=0)
    error_code = models.CharField(max_length=60, blank=True)


class PriceVersion(TeamScopedModel):
    model = models.ForeignKey(PoolModel, on_delete=models.PROTECT, related_name='prices')
    effective_from = models.DateTimeField('生效时间')
    input_rate = models.DecimalField('输入 / 百万 token', max_digits=14, decimal_places=6, validators=NONNEGATIVE)
    output_rate = models.DecimalField('输出 / 百万 token', max_digits=14, decimal_places=6, validators=NONNEGATIVE)
    cached_rate = models.DecimalField('缓存读取 / 百万 token', max_digits=14, decimal_places=6, validators=NONNEGATIVE)
    cache_write_rate = models.DecimalField('缓存写入 / 百万 token', max_digits=14, decimal_places=6, validators=NONNEGATIVE)
    currency = models.CharField('币种', max_length=3, choices=[('CNY','CNY'),('USD','USD')], default='CNY')
    cny_exchange_rate = models.DecimalField('折算人民币汇率', max_digits=12, decimal_places=6,
        default=Decimal('1'), validators=[MinValueValidator(Decimal('0.000001'))])
    source = models.CharField('价格来源', max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta: ordering = ['-effective_from', '-pk']


class DailyPrice(TeamScopedModel):
    model = models.ForeignKey(PoolModel, on_delete=models.PROTECT, related_name='daily_prices')
    day = models.DateField()
    price = models.ForeignKey(PriceVersion, on_delete=models.PROTECT, null=True)
    status = models.CharField(max_length=16, choices=[('verified','来源已核对'),('manual','沿用管理员价格'),('failed','更新失败')])
    note = models.CharField(max_length=300, blank=True)
    checked_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-day', '-pk']
        constraints = [models.UniqueConstraint(fields=['model', 'day'], name='pool_price_once_daily')]


class PoolSettings(TeamScopedModel):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name='owned_api_pools')
    weekly_limit = models.DecimalField('团队每周额度（元，留空不限制）', max_digits=12, decimal_places=2, null=True, blank=True, validators=NONNEGATIVE)
    default_weekly_limit = models.DecimalField('成员默认每周额度（元，留空不限制）', max_digits=12, decimal_places=2, null=True, blank=True, default=10, validators=NONNEGATIVE)
    monthly_limit = models.DecimalField('团队每月额度（元）', max_digits=12, decimal_places=2, null=True, blank=True, validators=NONNEGATIVE)
    default_member_limit = models.DecimalField('成员默认每月额度（元）', max_digits=12, decimal_places=2, null=True, blank=True, validators=NONNEGATIVE)
    max_call_cost = models.DecimalField('单次调用最高预留（元）', max_digits=10, decimal_places=2, default=10, validators=NONNEGATIVE)
    enabled = models.BooleanField('开放调用', default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['workspace'], name='pool_settings_per_team')]



class Allowance(TeamScopedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='api_allowances')
    monthly_limit = models.DecimalField('每月额度（元）', max_digits=12, decimal_places=2, null=True, blank=True, validators=NONNEGATIVE)
    weekly_limit = models.DecimalField('每周额度（元，留空不限制）', max_digits=12, decimal_places=2, null=True, blank=True, validators=NONNEGATIVE)
    enabled = models.BooleanField('允许调用', default=True)
    preferred_model = models.ForeignKey(PoolModel,on_delete=models.SET_NULL,null=True,blank=True,related_name='+')
    history_days = models.PositiveIntegerField('AI 对话保留天数（0 表示自行删除）', default=0)
    extra_balance = models.DecimalField('额外额度余额（元）', max_digits=18, decimal_places=8, default=0)
    extra_reserved = models.DecimalField('额外额度预留（元）', max_digits=18, decimal_places=8, default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['workspace','user'], name='allowance_per_team')]



class PointGrant(TeamScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='point_grants')
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    amount_cny = models.DecimalField(max_digits=18, decimal_places=8, validators=NONNEGATIVE)
    created_at = models.DateTimeField(auto_now_add=True)


class ResetCard(TeamScopedModel):
    """A member-owned, single-use entitlement; provider billing is unaffected."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch_id = models.UUIDField()
    ordinal = models.PositiveSmallIntegerField(default=0)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='quota_reset_cards')
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    period = models.CharField(max_length=8, choices=[('week', '本周额度'), ('month', '本月额度'), ('both', '本周与本月额度')], default='week')
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['expires_at', 'created_at']
        constraints = [models.UniqueConstraint(fields=['workspace', 'batch_id', 'user', 'ordinal'], name='reset_card_issue_once')]


class QuotaReset(TeamScopedModel):
    scope = models.CharField(max_length=60)
    period = models.CharField(max_length=8)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, related_name='+')
    card = models.OneToOneField(ResetCard, on_delete=models.PROTECT, null=True, blank=True)
    reason = models.CharField(max_length=200, blank=True)
    restored_cny = models.DecimalField(max_digits=18, decimal_places=8, default=0)
    restored_periods = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-pk']


class PointGift(TeamScopedModel):
    """Escrow for virtual AI points; gifting never changes provider billing."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='sent_point_gifts')
    message = models.OneToOneField('core.ChatMessage', on_delete=models.PROTECT, related_name='point_gift')
    kind = models.CharField(max_length=12, choices=[('transfer','积分转账'),('packet','积分红包')])
    mode = models.CharField(max_length=12, default='equal', choices=[('equal','均分'),('random','拼手气')])
    amount_cny = models.DecimalField(max_digits=18, decimal_places=8)
    remaining_cny = models.DecimalField(max_digits=18, decimal_places=8)
    count = models.PositiveIntegerField(default=1)
    claimed_count = models.PositiveIntegerField(default=0)
    greeting = models.CharField(max_length=80, default='科研顺利！')
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    refunded_cny = models.DecimalField(max_digits=18, decimal_places=8, default=0)
    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(amount_cny__gt=0,remaining_cny__gte=0,count__gte=1,count__lte=100),name='valid_point_gift')]


class PointGiftReceipt(TeamScopedModel):
    gift = models.ForeignKey(PointGift, on_delete=models.PROTECT, related_name='receipts')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='point_gift_receipts')
    amount_cny = models.DecimalField(max_digits=18, decimal_places=8)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['gift','user'],name='one_point_gift_receipt')]


class ApiRateWindow(TeamScopedModel):
    """Ephemeral counters and leases, not a request or operation log."""
    scope = models.CharField(max_length=80)
    minute = models.PositiveBigIntegerField(default=0)
    requests = models.PositiveIntegerField(default=0)
    leases = models.JSONField(default=dict)
    expires_at = models.DateTimeField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['workspace','scope'], name='rate_scope_per_team')]



class BudgetMonth(TeamScopedModel):
    generation = models.PositiveBigIntegerField(default=0)
    scope = models.CharField(max_length=60)
    month = models.DateField()
    spent = models.DecimalField(max_digits=18, decimal_places=8, default=0)
    reserved = models.DecimalField(max_digits=18, decimal_places=8, default=0)
    reset_credit = models.DecimalField(max_digits=18, decimal_places=8, default=0)
    reset_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['workspace','scope','month'], name='pool_unique_month_budget')]


class BudgetWeek(TeamScopedModel):
    generation = models.PositiveBigIntegerField(default=0)
    base_limit_snapshot = models.DecimalField(max_digits=18, decimal_places=8, null=True, blank=True)
    base_limit_recorded = models.BooleanField(default=False)
    scope = models.CharField(max_length=60)
    week = models.DateField()
    spent = models.DecimalField(max_digits=18, decimal_places=8, default=0)
    reserved = models.DecimalField(max_digits=18, decimal_places=8, default=0)
    reset_credit = models.DecimalField(max_digits=18, decimal_places=8, default=0)
    reset_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['workspace','scope','week'], name='pool_unique_week_budget')]


class MemberToken(TeamScopedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='pool_tokens')
    experiment = models.ForeignKey('core.Experiment',on_delete=models.SET_NULL,null=True,blank=True,related_name='member_api_keys')
    experiment_bound = models.BooleanField(default=False)
    project = models.ForeignKey('core.Project',on_delete=models.SET_NULL,null=True,blank=True,related_name='member_api_keys')
    project_bound = models.BooleanField(default=False)
    label = models.CharField('凭证名称', max_length=80)
    digest = models.CharField(max_length=64, unique=True)
    prefix = models.CharField(max_length=16)
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    allowed_models = models.JSONField(default=list, blank=True)
    cost_limit_cny = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, validators=NONNEGATIVE)
    last_used_at = models.DateTimeField(null=True, blank=True)


class Call(TeamScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='api_calls')
    api_token = models.ForeignKey(MemberToken, on_delete=models.PROTECT, null=True, blank=True, related_name='calls')
    quota_generations = models.JSONField(default=dict, editable=False)
    model = models.ForeignKey(PoolModel, on_delete=models.PROTECT)
    price = models.ForeignKey(PriceVersion, on_delete=models.PROTECT)
    project = models.ForeignKey('core.Project', on_delete=models.PROTECT, null=True, blank=True, related_name='api_calls')
    experiment = models.ForeignKey('core.Experiment', on_delete=models.PROTECT, null=True, blank=True, related_name='api_calls')
    group_id = models.UUIDField(null=True, blank=True, db_index=True)
    purpose = models.CharField(max_length=16, default='api', choices=[('api','API 调用'),('assistant','AI 助手')])
    status = models.CharField(max_length=16, default='running', choices=[('running','调用中'),('success','已计量'),('failed','未计费失败'),('unknown','费用待核对')])
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    heartbeat_at = models.DateTimeField(default=timezone.now, db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    input_tokens = models.PositiveIntegerField(null=True, blank=True)
    output_tokens = models.PositiveIntegerField(null=True, blank=True)
    cached_tokens = models.PositiveIntegerField(null=True, blank=True)
    cache_write_tokens = models.PositiveIntegerField(null=True, blank=True)
    reasoning_tokens = models.PositiveIntegerField(null=True, blank=True)
    cost = models.DecimalField(max_digits=18, decimal_places=8, null=True, blank=True)
    cost_cny = models.DecimalField(max_digits=18, decimal_places=8, null=True, blank=True)
    reserved_cny = models.DecimalField(max_digits=18, decimal_places=8, default=0)
    extra_reserved_cny = models.DecimalField(max_digits=18, decimal_places=8, default=0)
    extra_cost_cny = models.DecimalField(max_digits=18, decimal_places=8, null=True, blank=True)
    budget_month = models.DateField()
    budget_week = models.DateField(null=True, blank=True)
    latency_ms = models.PositiveIntegerField(default=0)
    provider_request_id = models.CharField(max_length=200, blank=True)
    error_code = models.CharField(max_length=60, blank=True)
    reconciled = models.BooleanField(default=False)
    # No prompts, responses, tool contents or provider keys are stored in the billing table.

    class Meta:
        ordering = ['-created_at', '-pk']
        indexes = [models.Index(fields=['user','-created_at','-id'],name='call_user_recent'),models.Index(fields=['experiment','-created_at','-id'],name='call_experiment_recent')]


class AssistantConversation(TeamScopedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='assistant_conversations')
    title = models.CharField(max_length=100, default='新对话')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at', '-pk']


class AgentGrant(models.Model):
    """A person's bounded delegation; never a replacement for business access."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    project = models.ForeignKey('core.Project', on_delete=models.PROTECT)
    actions = models.JSONField(default=list)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    max_operations = models.PositiveSmallIntegerField(default=20)
    used_operations = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=['user', 'expires_at'], name='agent_grant_user_expiry')]
        constraints = [models.CheckConstraint(condition=models.Q(max_operations__gte=1, max_operations__lte=30,
            used_operations__lte=models.F('max_operations')), name='agent_grant_operation_bound')]


class AgentPluginSetting(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    plugin = models.CharField(max_length=60)
    enabled = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'plugin'], name='agent_plugin_user_unique')]


class AssistantJob(TeamScopedModel):
    authorization = models.ForeignKey(AgentGrant, on_delete=models.PROTECT, null=True, blank=True)
    operation_group = models.UUIDField(default=uuid.uuid4, editable=False)
    billing_workspace = models.ForeignKey('core.Workspace', on_delete=models.PROTECT, null=True, blank=True, related_name='funded_assistant_jobs')
    retry_of = models.ForeignKey('self',null=True,blank=True,on_delete=models.SET_NULL,related_name='retries')
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    conversation = models.ForeignKey(AssistantConversation, on_delete=models.CASCADE, null=True, blank=True, related_name='jobs')
    user_text = models.TextField(blank=True)
    images = models.ManyToManyField('AssistantImage', blank=True, related_name='jobs')
    context = models.JSONField(null=True, blank=True)
    preferences = models.JSONField(default=dict)
    heartbeat_at = models.DateTimeField(default=timezone.now)
    state = models.CharField(max_length=16, default='running')
    cancel_requested = models.BooleanField(default=False)
    activity = models.JSONField(default=list)
    result = models.JSONField(default=dict)
    # Private execution state lives with the conversation, never in billing rows.
    execution = models.JSONField(default=dict, editable=False)
    event_sequence = models.PositiveBigIntegerField(default=0, editable=False)
    lease_token = models.UUIDField(null=True, editable=False)
    lease_expires_at = models.DateTimeField(null=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True)
    class Meta:
        indexes = [models.Index(fields=['conversation','-created_at','-id'],name='assistant_job_recent'),
            models.Index(fields=['state','lease_expires_at','created_at'],name='assistant_job_queue')]

    def save(self, *args, **kwargs):
        from django.db import transaction
        creating=self._state.adding
        with transaction.atomic(using=kwargs.get('using') or self._state.db or 'default'):
            super().save(*args, **kwargs)
            if creating:AssistantJobOrder.objects.using(self._state.db).get_or_create(job=self)



class AssistantJobOrder(TeamScopedModel):
    # Keep public UUIDs and retry IDs unchanged; this auto ID orders creation ties.
    job = models.OneToOneField(AssistantJob, on_delete=models.CASCADE, related_name='creation_order')


class AssistantEvent(TeamScopedModel):
    """Ordered step boundaries; token deltas remain a replaceable UI snapshot."""
    job = models.ForeignKey(AssistantJob, on_delete=models.CASCADE, related_name='events')
    sequence = models.PositiveBigIntegerField()
    kind = models.CharField(max_length=40)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        default_manager_name = 'objects'
        base_manager_name = 'all_objects'
        constraints = [models.UniqueConstraint(fields=['job', 'sequence'], name='assistant_event_sequence')]
        ordering = ['sequence']


class AssistantInput(TeamScopedModel):
    """Private, idempotent steering received while one assistant turn runs."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(AssistantJob, on_delete=models.CASCADE, related_name='inputs')
    request_id = models.UUIDField()
    sequence = models.PositiveBigIntegerField()
    text = models.TextField()
    state = models.CharField(max_length=12, default='queued', choices=[
        ('queued', '等待处理'), ('applied', '已接收'), ('discarded', '未处理')])
    created_at = models.DateTimeField(auto_now_add=True)
    applied_at = models.DateTimeField(null=True)

    class Meta:
        default_manager_name = 'objects'
        base_manager_name = 'all_objects'
        ordering = ['sequence']
        constraints = [models.UniqueConstraint(fields=['job','request_id'], name='assistant_input_request'),
            models.UniqueConstraint(fields=['job','sequence'], name='assistant_input_sequence')]


class AgentOperation(models.Model):
    """A committed local command and its receipt share one database transaction."""
    group = models.UUIDField()
    key = models.CharField(max_length=64)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    project = models.ForeignKey('core.Project', on_delete=models.PROTECT)
    grant = models.ForeignKey(AgentGrant, on_delete=models.PROTECT)
    tool = models.CharField(max_length=80)
    result = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['group', 'key'], name='agent_operation_once')]


class AssistantImage(TeamScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    data = models.TextField(editable=False)
    width = models.PositiveIntegerField()
    height = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
