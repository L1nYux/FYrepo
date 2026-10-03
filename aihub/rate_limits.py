"""Database-backed per-account and per-token gates shared by WSGI workers."""
import time
import uuid
from contextlib import contextmanager
from django.db import transaction, OperationalError
from django.db.models import F
from django.utils import timezone
from .models import ApiRateWindow


class RateLimited(Exception):
    pass


@contextmanager
def gate(user, token):
    scopes = sorted([(f'user:{user.pk}', 60, 3), (f'token:{token.pk}', 30, 2)])
    now = time.time()
    lease = uuid.uuid4().hex
    with transaction.atomic():
        ApiRateWindow.objects.filter(scope__in=[scope for scope, _, _ in scopes]).update(requests=F('requests'))
        for scope, requests, concurrent in scopes:
            row, _ = ApiRateWindow.objects.get_or_create(scope=scope, defaults={'expires_at':timezone.now()})
            # Obtain SQLite's writer lock before reading; FOR UPDATE also covers PostgreSQL.
            ApiRateWindow.objects.filter(pk=row.pk).update(requests=F('requests'))
            row = ApiRateWindow.objects.select_for_update().get(pk=row.pk)
            row.leases = {key: value for key, value in row.leases.items() if value > now}
            if row.minute != int(now // 60):
                row.minute, row.requests = int(now // 60), 0
            if row.requests >= requests or len(row.leases) >= concurrent:
                raise RateLimited('请求过于频繁或已有调用正在执行，请稍后重试。')
            row.requests += 1
            row.leases[lease] = now + 300
            row.expires_at = timezone.now() + timezone.timedelta(minutes=10)
            row.save(update_fields=['minute','requests','leases','expires_at'])
        ApiRateWindow.objects.filter(expires_at__lt=timezone.now()).delete()
    try:
        yield
    finally:
        try:
            with transaction.atomic():
                for scope, _, _ in scopes:
                    ApiRateWindow.objects.filter(scope=scope).update(requests=F('requests'))
                    row = ApiRateWindow.objects.select_for_update().filter(scope=scope).first()
                    if row:
                        row.leases.pop(lease, None)
                        row.save(update_fields=['leases'])
        except OperationalError:
            # A settled provider response must not become an error because cleanup
            # encountered a temporary lock. An abandoned lease expires in 5 minutes.
            pass
