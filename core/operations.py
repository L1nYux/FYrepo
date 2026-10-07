"""Small operational endpoints; error pages deliberately avoid database context."""
import logging
from django.db import connection
from django.http import JsonResponse, HttpResponse
from django.template import loader
from django.views.decorators.http import require_GET


@require_GET
def healthz(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
        return JsonResponse({'status': 'ok'})
    except Exception:
        logging.getLogger(__name__).exception('Readiness check failed')
        return JsonResponse({'status': 'unavailable'}, status=503)


def not_found(request, exception):
    return HttpResponse(loader.get_template('404.html').render({}), status=404)


def server_error(request):
    return HttpResponse(loader.get_template('500.html').render({}), status=500)
