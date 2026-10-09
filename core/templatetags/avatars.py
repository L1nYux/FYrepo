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
        number = number.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        return format(number if number else Decimal('0.00'), '.2f')
    except (InvalidOperation, ValueError, TypeError): return ''

from core.identity import nickname, account_id
register.filter('nickname',nickname)
register.filter('account_id',account_id)

@register.filter
def conversation_date(value):
    from django.utils import timezone
    if not value: return ''
    date = timezone.localtime(value) if timezone.is_aware(value) else value
    days = (timezone.localdate() - date.date()).days
    if days == 0: return date.strftime('%H:%M')
    if days == 1: return '昨天'
    if days == 2: return '前天'
    return (str(date.year)+'/' if date.year != timezone.localdate().year else '')+str(date.month)+'/'+str(date.day)
