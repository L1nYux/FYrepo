"""Regressions found during the 0.2.19 review; all accounts are disposable."""
from datetime import timedelta
from unittest.mock import patch
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from .models import Team, TeamApplication, PersonalMessage
from .recruitment import ListingForm
from . import test_community


class Revision019Tests(TestCase):
    setUp = test_community.CommunityTests.setUp
    prepare_application = test_community.CommunityTests.prepare_application

    def test_listing_save_preserves_concurrent_platform_capacity_change(self):
        validate = ListingForm.is_valid
        def concurrent_edit(form):
            valid = validate(form)
            Team.objects.filter(pk=self.team.pk).update(member_limit=11)
            return valid
        with patch.object(ListingForm, 'is_valid', concurrent_edit):
            response = self.client.post(reverse('recruitment_manage'), {
                'action': 'listing', 'listed': 'on', 'introduction': '新介绍', 'research_area': '科研'})
        self.assertEqual(response.status_code, 302)
        self.team.refresh_from_db()
        self.assertEqual(self.team.member_limit, 11)
        self.assertEqual(self.team.introduction, '新介绍')

    def test_duplicate_application_reports_error_without_breaking_transaction(self):
        item = self.prepare_application()
        response = self.client.post(reverse('team_apply', args=[item.opening_id]), {'resume': '再次投递'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '已投递过该职位')
        self.assertEqual(TeamApplication.objects.count(), 1)

    def test_personal_cursor_does_not_skip_messages_when_clock_moves_back(self):
        rows = PersonalMessage.objects.bulk_create([
            PersonalMessage(sender=self.owner, recipient=self.worker, body=str(i)) for i in range(101)])
        PersonalMessage.objects.filter(pk=rows[-1].pk).update(created_at=timezone.now()-timedelta(days=1))
        url = reverse('personal_chat', args=[self.worker.pk])
        first = self.client.get(url, HTTP_ACCEPT='application/json').json()['messages']
        self.assertEqual([row['id'] for row in first], [row.pk for row in rows[:100]])
        second = self.client.get(url, {'after': first[-1]['id']}, HTTP_ACCEPT='application/json').json()['messages']
        self.assertEqual([row['id'] for row in second], [rows[-1].pk])

    def test_invalid_cursor_is_rejected_before_message_is_sent(self):
        url = reverse('personal_chat', args=[self.worker.pk]) + '?after=invalid'
        response = self.client.post(url, {'body': '不应发送'}, HTTP_ACCEPT='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(PersonalMessage.objects.exists())
