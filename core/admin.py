"""Django 管理后台。日常工作台已经覆盖的流程不必在这里重复操作，
这里主要用于排障：查看原始数据、补附件、停用账号。"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from django.db.models import Q

from .models import (Attachment, ChatMessage, Comment, ExpenseClaim, FinanceEntry, Invite,
                     MemberProfile, Project, Submission, Task)

admin.site.unregister(User)


@admin.register(User)
class AccountAdmin(UserAdmin):
    def has_delete_permission(self, request, obj=None):
        return False  # 停用账号，不删除历史归属。


class AttachmentInline(admin.TabularInline):
    model = Attachment
    extra = 0
    fields = ('file', 'original_name', 'uploaded_by')


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'owner', 'status', 'budget', 'created_at', 'archived_at')
    list_filter = ('status',)
    search_fields = ('name', 'goal')
    filter_horizontal = ('members',)


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ('title', 'project', 'parent', 'assignee', 'status', 'progress', 'due_date')
    list_filter = ('status', 'project')
    search_fields = ('title', 'description')


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = ('task', 'author', 'status', 'is_final', 'created_at')
    list_filter = ('status', 'is_final')
    search_fields = ('summary',)
    inlines = [AttachmentInline]


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ('task', 'kind', 'author', 'created_at')
    list_filter = ('kind',)
    inlines = [AttachmentInline]


@admin.register(FinanceEntry)
class FinanceEntryAdmin(admin.ModelAdmin):
    list_display = ('occurred_on', 'kind', 'amount', 'project', 'created_by', 'voided_at')
    list_filter = ('kind', 'project')
    inlines = [AttachmentInline]


@admin.register(ExpenseClaim)
class ExpenseClaimAdmin(admin.ModelAdmin):
    list_display = ('applicant', 'amount', 'occurred_on', 'project', 'status', 'reviewed_by', 'created_at')
    list_filter = ('status', 'project')
    inlines = [AttachmentInline]


@admin.register(Invite)
class InviteAdmin(admin.ModelAdmin):
    list_display = ('pk', 'created_by', 'created_at', 'expires_at', 'used_by', 'state')

    def has_add_permission(self, request):
        return False  # 邀请码在“人员 → 邀请码”页面生成。

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(MemberProfile)
class MemberProfileAdmin(admin.ModelAdmin):
    """账号层级（开发者／普通用户）；管理员仍由 is_staff 表示。"""

    list_display = ('user', 'tier', 'created_at')
    list_filter = ('tier',)
    search_fields = ('user__username',)


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ('room', 'author', 'created_at')
    list_filter = ('room',)
    search_fields = ('body', 'author__username')

    def get_queryset(self, request):
        return super().get_queryset(request).filter(
            Q(recipient__isnull=True) | Q(author=request.user) | Q(recipient=request.user))

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
