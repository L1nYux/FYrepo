"""Purge only content acknowledged by every original recipient at least 30 days ago."""
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone
from core.models import LocalChatDelivery, PersonalMessage, GroupMessage


class Command(BaseCommand):
    help = 'Preview 30-day delivered ordinary chat cleanup; --apply performs it.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--limit', type=int, default=500)

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=30)
        candidates = LocalChatDelivery.objects.filter(fully_received_at__lte=cutoff, purged_at__isnull=True).order_by('pk')
        # Binary attachments, stickers and linked resources are not yet copied
        # into the phone archive. Keep their server source intact.
        personal = PersonalMessage.objects.filter(legacy_message__isnull=True, sticker__isnull=True, references=[]).exclude(uploads__isnull=False)
        groups = GroupMessage.objects.filter(group__is_default=False, sticker__isnull=True, references=[]).exclude(uploads__isnull=False)
        candidates = candidates.filter(Q(kind='personal', message_id__in=personal.values('pk')) | Q(kind='group', message_id__in=groups.values('pk')))
        removed = 0
        for identifier in candidates.values_list('pk', flat=True)[:max(1, min(options['limit'], 5000))]:
            with transaction.atomic():
                if options['apply']:
                    LocalChatDelivery.objects.filter(pk=identifier).update(created_at=F('created_at'))
                receipt = LocalChatDelivery.objects.select_for_update().get(pk=identifier)
                if receipt.purged_at or not receipt.fully_received_at or receipt.fully_received_at > cutoff or not receipt.recipients or not all(str(user) in receipt.received for user in receipt.recipients):
                    continue
                # Financial messages and legacy records never enter this policy.
                if receipt.kind == 'personal':
                    message = PersonalMessage.objects.filter(pk=receipt.message_id, legacy_message__isnull=True).first()
                else:
                    message = GroupMessage.objects.filter(pk=receipt.message_id, group_id=receipt.group_id, group__is_default=False).first()
                if message is None or message.uploads.exists() or message.sticker_id or message.references:
                    continue
                if options['apply']:
                    message.delete()
                    receipt.purged_at = timezone.now()
                    receipt.save(update_fields=['purged_at'])
                removed += 1
        self.stdout.write(f'{"Purged" if options["apply"] else "Eligible (preview only)"}: {removed} ordinary messages. Attachments and financial records preserved.')
