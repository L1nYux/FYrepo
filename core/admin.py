from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User

from .models import AuditEvent


admin.site.unregister(User)


@admin.register(User)
class AccountAdmin(UserAdmin):
    def save_model(self, request, obj, form, change):
        from .models import AuditEvent
        super().save_model(request, obj, form, change)
        AuditEvent.record(request.user, 'account.update' if change else 'account.create', f'user:{obj.pk}',
                          username=obj.username, is_active=obj.is_active, is_staff=obj.is_staff)

    def has_delete_permission(self, request, obj=None):
        return False  # Disable accounts instead of deleting historical ownership.


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'actor', 'action', 'target')
    list_filter = ('action', 'created_at')
    search_fields = ('action', 'target', 'actor__username')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
