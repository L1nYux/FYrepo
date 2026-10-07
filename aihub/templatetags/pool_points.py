from decimal import Decimal, InvalidOperation
from django import template

register = template.Library()


@register.filter
def points(value):
    if value is None or value == '': return ''
    try: return Decimal(str(value)) * 100
    except (InvalidOperation, ValueError, TypeError): return ''
