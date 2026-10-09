"""Read-only billing evidence for one call; never retries or reconciles it."""
import json
import uuid
from django.core.management.base import BaseCommand, CommandError
from aihub.models import Call
from aihub.timeouts import CONNECT_SECONDS, READ_SECONDS, STREAM_TOTAL_SECONDS, ASSISTANT_TOTAL_SECONDS


class Command(BaseCommand):
    help = '只读查看调用状态、上游编号、计量、价格快照和预留费用'

    def add_arguments(self, parser):
        parser.add_argument('call_id', type=uuid.UUID)

    def handle(self, *args, **options):
        fields = ['id', 'workspace_id', 'created_at', 'finished_at', 'latency_ms',
                  'status', 'error_code', 'provider_request_id', 'reconciled',
                  'model_id', 'model__model_id', 'model__provider_id',
                  'model__provider__name', 'input_tokens', 'output_tokens',
                  'cached_tokens', 'cache_write_tokens', 'reasoning_tokens',
                  'reserved_cny', 'extra_reserved_cny', 'cost', 'cost_cny',
                  'price_id', 'price__currency', 'price__cny_exchange_rate',
                  'price__input_rate', 'price__output_rate', 'price__cached_rate',
                  'price__cache_write_rate']
        row = Call.all_objects.filter(pk=options['call_id']).values(*fields).first()
        if not row:
            raise CommandError('当前数据库没有这笔调用，请确认连接的是生产环境。')
        self.stdout.write(json.dumps({'call': row, 'current_configuration': {
            'connect_seconds': CONNECT_SECONDS, 'idle_seconds': READ_SECONDS,
            'stream_total_seconds': STREAM_TOTAL_SECONDS,
            'assistant_total_seconds': ASSISTANT_TOTAL_SECONDS},
            'upstream_status': '未向上游发起查询，需根据上游编号或时间核对厂商账单',
            'billing_note': 'cost_cny=null 表示未知费用；预留额度不是已扣费用',
            'mutations': False, 'paid_requests_sent': 0}, ensure_ascii=False, default=str, indent=2))
