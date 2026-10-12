"""Database-backed per-account and per-token gates shared by WSGI workers."""
import time
import threading
import uuid
from contextlib import contextmanager
from django.db import transaction, OperationalError, close_old_connections, connections
from django.db.models import F
from django.utils import timezone
from .models import ApiRateWindow
from .timeouts import CONNECT_SECONDS, READ_SECONDS


class RateLimited(Exception):
    pass


@contextmanager
def gate(user, token):
    from .service import pool_settings
    config=pool_settings()
    scopes = sorted([(f'user:{user.pk}', config.account_rpm, config.account_concurrent),
                     (f'token:{token.pk}', config.key_rpm, config.key_concurrent)])
    now = time.time()
    lease = uuid.uuid4().hex
    lifetime=max(300,(READ_SECONDS or 1800)+CONNECT_SECONDS+120)
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
            if requests and row.requests >= requests or concurrent and len(row.leases) >= concurrent:
                raise RateLimited('请求过于频繁或已有调用正在执行，请稍后重试。')
            row.requests += 1
            row.leases[lease] = now + lifetime
            row.expires_at = timezone.now() + timezone.timedelta(seconds=lifetime+60)
            row.save(update_fields=['minute','requests','leases','expires_at'])
        ApiRateWindow.objects.filter(expires_at__lt=timezone.now()).delete()
    # Resolve the authorized scope on the request connection. The lease thread
    # must not lazily fetch a relation while that caller owns a SQLite write lock.
    selected_workspace=token.workspace
    stopped=threading.Event()
    def renew():
        from core.tenancy import scope as workspace_scope
        try:
            with workspace_scope(selected_workspace):
                while not stopped.wait(30):
                    close_old_connections()
                    try:
                        with transaction.atomic():
                            for scope, _, _ in scopes:
                                ApiRateWindow.objects.filter(scope=scope).update(requests=F('requests'))
                                row=ApiRateWindow.objects.select_for_update().filter(scope=scope).first()
                                if row and lease in row.leases:
                                    row.leases[lease]=time.time()+lifetime
                                    row.expires_at=timezone.now()+timezone.timedelta(seconds=lifetime+60)
                                    row.save(update_fields=['leases','expires_at'])
                    except OperationalError: pass
        finally: connections.close_all()
    worker=threading.Thread(target=renew,name='api-rate-lease',daemon=True);worker.start()
    try:
        yield
    finally:
        stopped.set();worker.join(timeout=2)
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
            # encountered a temporary lock. An abandoned lease expires after the inference idle timeout.
            pass
