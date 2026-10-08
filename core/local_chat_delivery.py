"""Durable receipt acknowledgments for phone-owned ordinary conversation history."""
import json
import re
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import F
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST
from .models import LocalChatDelivery, PersonalMessage, GroupMessage, GroupMember


@receiver(post_save, sender=PersonalMessage)
def personal_snapshot(sender, instance, created, raw=False, **kwargs):
    if not created or raw or instance.legacy_message_id:
        return
    LocalChatDelivery.objects.get_or_create(kind='personal', message_id=instance.pk,
        defaults={'recipients': sorted({instance.sender_id, instance.recipient_id})})


@receiver(post_save, sender=GroupMessage)
def group_snapshot(sender, instance, created, raw=False, **kwargs):
    if not created or raw or instance.group.is_default:
        return
    recipients = set(GroupMember.objects.filter(group=instance.group, active=True).values_list('user_id', flat=True))
    recipients.add(instance.author_id)
    LocalChatDelivery.objects.get_or_create(kind='group', message_id=instance.pk,
        defaults={'group_id': instance.group_id, 'recipients': sorted(recipients)})


def channel(request, value):
    match = re.fullmatch(r'(person|group):([1-9][0-9]{0,17})', value or '')
    if not match:
        raise PermissionDenied
    kind, identifier = match[1], int(match[2])
    from .personal_messages import thread_rows
    rows, group, _, read = thread_rows(request, identifier, kind == 'group')
    if kind == 'person':
        receipts = LocalChatDelivery.objects.filter(kind='personal')
    else:
        if group.is_default:
            raise PermissionDenied
        receipts = LocalChatDelivery.objects.filter(kind='group', group_id=identifier)
    return rows, receipts, read.cleared_through


def identifiers(raw):
    if not isinstance(raw, list) or len(raw) > 200 or any(type(v) is not int or not 0 < v < 2**63 for v in raw):
        raise ValueError
    return sorted(set(raw))


@login_required
@never_cache
@require_POST
def acknowledge(request):
    try:
        if len(request.body) > 16000:
            raise ValueError
        data = json.loads(request.body)
        ids = identifiers(data.get('ids'))
        key = data.get('channel', '')
        rows, receipts, _ = channel(request, key)
    except (ValueError, TypeError, AttributeError):
        return JsonResponse({'error': '收取确认无效。'}, status=400)
    visible = set(rows.filter(pk__in=ids).values_list('pk', flat=True))
    now = timezone.now()
    with transaction.atomic():
        # Acquire SQLite's writer lock before reading mutable acknowledgments.
        receipts.filter(message_id__in=visible, purged_at__isnull=True).update(created_at=F('created_at'))
        for item in receipts.select_for_update().filter(message_id__in=visible, purged_at__isnull=True):
            recipients = item.recipients
            if request.user.pk not in recipients:
                continue
            if key.startswith('person:') and int(key.split(':')[1]) not in recipients:
                continue
            received = dict(item.received)
            received.setdefault(str(request.user.pk), now.isoformat())
            item.received = received
            if all(str(user) in received for user in recipients) and not item.fully_received_at:
                item.fully_received_at = now
            item.save(update_fields=['received', 'fully_received_at'])
    return JsonResponse({'received': sorted(visible), 'retention_days': 30})


@login_required
@never_cache
@require_GET
def state(request):
    try:
        ids = identifiers([int(v) for v in request.GET.get('known', '').split(',') if v])
        key = request.GET.get('channel', '')
        rows, receipts, cleared = channel(request, key)
    except (ValueError, TypeError):
        return JsonResponse({'error': '记录查询无效。'}, status=400)
    visible = set(rows.filter(pk__in=ids).values_list('pk', flat=True))
    purged = []
    for item in receipts.filter(message_id__in=ids, purged_at__isnull=False):
        if request.user.pk in item.recipients and (not key.startswith('person:') or int(key.split(':')[1]) in item.recipients):
            if item.message_id > cleared:
                purged.append(item.message_id)
    return JsonResponse({'visible': sorted(visible), 'purged': purged, 'cleared_through': cleared})
