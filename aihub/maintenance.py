"""Daily price snapshots and cleanup of temporary assistant results."""
import threading
import time
from django.db import close_old_connections, connections
from django.utils import timezone
from .models import AssistantJob, Call
from .prices import refresh_prices


def daily():
    count=refresh_prices()
    cutoff=timezone.now()-timezone.timedelta(minutes=5)
    AssistantJob.objects.filter(state='running',created_at__lt=cutoff).update(
        state='error',finished_at=timezone.now(),result={'error':'本轮已超时或服务重启，请重新提问。'})
    Call.objects.filter(status='running',created_at__lt=cutoff).update(
        status='unknown',error_code='interrupted',finished_at=timezone.now())
    AssistantJob.objects.filter(conversation__isnull=True,finished_at__lt=timezone.now()-timezone.timedelta(days=7)).delete()
    return count


def start_local_scheduler():
    def loop():
        while True:
            close_old_connections()
            try: daily()
            except Exception: pass  # Keep the app available; failed feeds are shown in DailyPrice.
            finally: connections.close_all()
            time.sleep(900)
    threading.Thread(target=loop,name='daily-api-prices',daemon=True).start()
