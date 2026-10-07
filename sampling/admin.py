from django.contrib import admin

from .models import CandidatePaper, SamplingArtifact, SamplingExperimentLink, SamplingRun


@admin.register(SamplingRun)
class SamplingRunAdmin(admin.ModelAdmin):
    list_display = ("name", "version", "project", "status", "created_by", "created_at")
    list_filter = ("status", "sampling_method")
    search_fields = ("name", "project__name", "run_fingerprint")

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and not (obj and obj.is_frozen)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CandidatePaper)
class CandidatePaperAdmin(admin.ModelAdmin):
    list_display = ("paper_id", "title", "journal", "year", "tier", "period", "eligibility_status", "decision", "sample_role")
    list_filter = ("eligibility_status", "decision", "sample_role", "tier", "period")
    search_fields = ("paper_id", "title", "journal", "candidate_key")

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and not (obj and obj.run.is_frozen)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class ReadOnlySamplingAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(SamplingArtifact, ReadOnlySamplingAdmin)
admin.site.register(SamplingExperimentLink, ReadOnlySamplingAdmin)
