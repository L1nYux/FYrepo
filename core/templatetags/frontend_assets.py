from django import template
from django.templatetags.static import static
from django.utils.html import format_html_join
from core.frontend_assets import page_features, scripts_for

register = template.Library()


@register.simple_tag(takes_context=True)
def app_assets(context):
    return format_html_join('\n', '<script src="{}" defer></script>',
                            ((static(path),) for path in scripts_for(page_features(context))))
