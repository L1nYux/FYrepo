from django import template
from core.avatars import avatar_url
register = template.Library()
register.simple_tag(avatar_url)

@register.filter
def point_display(value):
    from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
    try:
        number = Decimal(str(value))
        if not number.is_finite(): return ''
        number = number.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)
        text = format(number if number else Decimal(0), 'f')
        return text.rstrip('0').rstrip('.') if '.' in text else text
    except (InvalidOperation, ValueError, TypeError): return ''
