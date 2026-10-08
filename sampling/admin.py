from django.contrib import admin

from .models import CandidatePaper, SamplingArtifact, SamplingExperimentLink, SamplingRun


class ScopedSamplingAdmin(admin.ModelAdmin):
    def get_queryset(self, request):
        from core.resource_navigation import spaces
        path = 'workspace' if self.model == SamplingRun else 'run__workspace'
        return super().get_queryset(request).filter(**{path+'__in': spaces(request.user)})

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        if not super().has_change_permission(request,obj):
            return False
        if obj is None:
            return True
        from core.message_scope import select
        from .views import _can_manage
        run = obj if isinstance(obj,SamplingRun) else obj.run
        select(request,run.workspace_id)
        return _can_manage(request,run)

    def get_readonly_fields(self, request, obj=None):
        fields = ('created_by','workspace','source_run') if self.model == SamplingRun else ('run',)
        return (*super().get_readonly_fields(request,obj),*fields)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        from core.resource_navigation import spaces
        if db_field.name == 'project':
            from core.models import Project
            kwargs['queryset'] = Project.all_objects.filter(workspace__in=spaces(request.user),archived_at__isnull=True)
        if db_field.name in ('run','source_run'):
            kwargs['queryset'] = SamplingRun.objects.filter(workspace__in=spaces(request.user))
        return super().formfield_for_foreignkey(db_field,request,**kwargs)


@admin.register(SamplingRun)
class SamplingRunAdmin(ScopedSamplingAdmin):
    list_display = ("name", "version", "project", "status", "created_by", "created_at")
    list_filter = ("status", "sampling_method")
    search_fields = ("name", "project__name", "run_fingerprint")

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and not (obj and obj.is_frozen)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CandidatePaper)
class CandidatePaperAdmin(ScopedSamplingAdmin):
    list_display = ("paper_id", "title", "journal", "year", "tier", "period", "eligibility_status", "decision", "sample_role")
    list_filter = ("eligibility_status", "decision", "sample_role", "tier", "period")
    search_fields = ("paper_id", "title", "journal", "candidate_key")

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and not (obj and obj.run.is_frozen)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class ReadOnlySamplingAdmin(ScopedSamplingAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(SamplingArtifact, ReadOnlySamplingAdmin)
admin.site.register(SamplingExperimentLink, ReadOnlySamplingAdmin)
