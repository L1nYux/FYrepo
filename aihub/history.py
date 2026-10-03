"""Explicit member-controlled history retention; financial Calls are untouched."""
from django.db.models import Exists, OuterRef
from django.utils import timezone
from .models import Allowance, AssistantConversation, AssistantJob


def prune(user=None):
    policies = Allowance.objects.filter(history_days__gt=0)
    if user is not None:
        policies = policies.filter(user=user)
    for policy in policies:
        cutoff = timezone.now() - timezone.timedelta(days=policy.history_days)
        rows = AssistantConversation.objects.filter(user_id=policy.user_id, updated_at__lt=cutoff)
        rows.annotate(active=Exists(AssistantJob.objects.filter(conversation_id=OuterRef('pk'), state='running'))).filter(active=False).delete()
