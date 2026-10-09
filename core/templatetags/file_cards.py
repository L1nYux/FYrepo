from django import template
from core.file_preview import card
register=template.Library()

@register.filter
def attachment_card(item):
    return card(item,'attachment')
