from django import template
from core.avatars import avatar_url
register = template.Library()
register.simple_tag(avatar_url)

@register.filter
def point_display(value):
    from decimal import Decimal, InvalidOperation
    try:
        text = format(Decimal(str(value)), 'f')
        return text.rstrip('0').rstrip('.') if '.' in text else text
    except (InvalidOperation, ValueError, TypeError): return ''
