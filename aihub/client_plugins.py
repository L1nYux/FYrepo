"""Metadata for client capabilities; only the native client can change their settings."""
import json
from functools import lru_cache
from pathlib import Path
from django.conf import settings


@lru_cache(maxsize=1)
def definitions():
    rows=json.loads((Path(settings.BASE_DIR)/'static/core/client-plugins.json').read_text(encoding='utf-8'))
    return tuple({key:value for key,value in row.items() if key not in ('setting','action')} for row in rows)


def catalog():
    return [{**row,'runtime':'desktop','scope':'device','enabled':None,'available':False,'writes':False} for row in definitions()]
