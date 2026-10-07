"""Keep internal workflows in the workspace; public pages are explicit previews."""
from urllib.parse import unquote, urlsplit

from django.urls import Resolver404, resolve


def is_public_page(name):
    return (name.startswith('public_') and name != 'public_profile_edit') or name in (
        'contact', 'showcase', 'about')


def workspace_return_path(value):
    """Accept a resolved internal page, including its query and fragment."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value.startswith('/') or any(ord(char) < 32 for char in value):
        return None
    try:
        location = urlsplit(value)
    except ValueError:
        return None
    path = unquote(location.path)
    if location.netloc or location.scheme or path.startswith('//') or '\\' in path:
        return None
    try:
        name = resolve(path).url_name or ''
    except Resolver404:
        return None
    if is_public_page(name) or name in ('login', 'register', 'logout', 'desktop_api'):
        return None
    return value
