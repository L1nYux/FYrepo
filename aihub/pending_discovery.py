"""Short-lived server-only discovery proposals, never keys in browser tickets."""
import json
import os
import time
import uuid
from pathlib import Path
from django.conf import settings
from django.core.exceptions import ValidationError


def directory():
    root = Path(settings.DATA_DIR) / '.api-discovery'
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    return root


def cleanup():
    root = Path(settings.DATA_DIR) / '.api-discovery'
    if not root.exists():
        return
    for path in root.glob('*.json'):
        try:
            if path.stat().st_mtime < time.time() - 900:
                path.unlink(missing_ok=True)
        except FileNotFoundError:
            pass


def stage(value):
    root = directory()
    cleanup()
    identifier = uuid.uuid4().hex
    with os.fdopen(os.open(root / (identifier + '.json'), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w', encoding='utf-8') as output:
        json.dump({'expires': time.time() + 900, **value}, output)
    return identifier


def load(identifier, user):
    if not isinstance(identifier, str) or len(identifier) != 32 or any(c not in '0123456789abcdef' for c in identifier):
        raise ValidationError('模型列表已过期，请重新读取。')
    try:
        value = json.loads((directory() / (identifier + '.json')).read_text('utf-8'))
    except (OSError, ValueError):
        raise ValidationError('模型列表已过期，请重新读取。') from None
    if value.get('user') != user.pk or value.get('expires', 0) < time.time():
        raise ValidationError('模型列表已过期，请重新读取。')
    return value


def discard(identifier):
    if isinstance(identifier, str) and len(identifier) == 32 and all(c in '0123456789abcdef' for c in identifier):
        (directory() / (identifier + '.json')).unlink(missing_ok=True)
