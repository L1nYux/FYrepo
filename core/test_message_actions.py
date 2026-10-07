import json
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone
from aihub import agent
from .models import Attachment, ChatMessage, ChatReference
from .messages import unread_counts
from .tests import WorkbenchTestCase, scratch_dir


class MessageActionTests(WorkbenchTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.dev)
        self.other_client = Client()
        self.other_client.force_login(self.owner)
        self.message = ChatMessage.objects.create(room='private', author=self.dev,
                                                  recipient=self.owner, body='private draft')
        self.url = reverse('message_action', args=[self.message.pk])
        self.room = reverse('messages_private', args=[self.owner.pk])

    def test_withdraw_hides_content_and_preserves_background_reedit(self):
        payload = self.client.post(self.url, {'action':'withdraw'}).json()['message']
        self.assertTrue(payload['withdrawn'])
        self.assertEqual(payload['body'], '')
        page = self.client.get(self.room)
        self.assertContains(page, 'message-system-note')
        self.assertContains(page, '重新编辑')
        self.assertNotContains(page, 'private draft')
        self.assertNotContains(page, 'data-message-withdraw-notice')
        other_page = self.other_client.get(reverse('messages_private',args=[self.dev.pk]))
        self.assertNotContains(other_page, 'data-message-action="draft"')
        self.assertNotContains(other_page, 'private draft')

    def test_reedit_has_no_time_limit(self):
        self.message.withdrawn_at = timezone.now() - timezone.timedelta(days=30)
        self.message.save(update_fields=['withdrawn_at'])
        response = self.client.post(self.url, {'action':'draft'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['draft']['body'], 'private draft')

    def test_cannot_reedit_live_message(self):
        self.assertEqual(self.client.post(self.url, {'action':'draft'}).status_code, 400)

    def test_other_participant_cannot_withdraw_or_read_draft(self):
        for action in ('withdraw','draft'):
            self.assertEqual(self.other_client.post(self.url, {'action':action}).status_code, 403)

    def test_nonparticipant_including_admin_cannot_access_private_message(self):
        for user in (self.admin,self.outsider):
            self.client.force_login(user)
            for action in ('withdraw','draft','delete'):
                self.assertEqual(self.client.post(self.url, {'action':action}).status_code, 404)

    def test_delete_is_personal_and_persistent(self):
        self.assertEqual(self.client.post(self.url, {'action':'delete'}).status_code, 200)
        self.assertNotContains(self.client.get(self.room), 'private draft')
        self.assertContains(self.other_client.get(reverse('messages_private',args=[self.dev.pk])), 'private draft')
        self.assertTrue(ChatMessage.objects.filter(pk=self.message.pk).exists())
        self.assertEqual(self.client.post(self.url, {'action':'draft'}).status_code, 404)

    def test_delete_removes_withdrawal_note(self):
        self.client.post(self.url, {'action':'withdraw'})
        self.client.post(self.url, {'action':'delete'})
        self.assertNotContains(self.client.get(self.room), 'message-system-note')

    def test_poll_updates_old_withdrawn_message_without_body(self):
        self.client.post(self.url, {'action':'withdraw'})
        data = self.other_client.get(reverse('messages_private_poll',args=[self.dev.pk]),
            {'after':self.message.pk,'known':str(self.message.pk)}).json()
        self.assertEqual(data['messages'], [])
        self.assertEqual(data['updates'][0]['id'], self.message.pk)
        self.assertTrue(data['updates'][0]['withdrawn'])
        self.assertEqual(data['updates'][0]['body'], '')

    def test_poll_removes_personally_deleted_message(self):
        self.client.post(self.url, {'action':'delete'})
        data = self.client.get(reverse('messages_private_poll',args=[self.owner.pk]),
            {'after':0,'known':str(self.message.pk)}).json()
        self.assertEqual(data['removed'], [self.message.pk])
        self.assertEqual(data['messages'], [])

    def test_withdraw_and_delete_remove_unread(self):
        self.assertEqual(unread_counts(self.owner)['dm:'+str(self.dev.pk)], 1)
        self.other_client.post(self.url, {'action':'delete'})
        self.assertEqual(unread_counts(self.owner), {})
        self.client.post(self.url, {'action':'withdraw'})
        self.assertEqual(unread_counts(self.owner), {})

    def test_ajax_send_returns_message_and_validates_empty(self):
        response = self.client.post(self.room, {'body':'hello','references':'[]'}, HTTP_ACCEPT='application/json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['message']['body'], 'hello')
        self.assertTrue(response.json()['message']['mine'])
        self.assertEqual(self.client.post(self.room, {'body':' ','references':'[]'}, HTTP_ACCEPT='application/json').status_code, 400)

    def test_resend_cannot_use_other_conversation_or_other_authors_message(self):
        self.client.post(self.url, {'action':'withdraw'})
        response = self.client.post(reverse('messages_hub'), {'body':'copy','resend_message':self.message.pk})
        self.assertEqual(response.status_code, 404)
        response = self.other_client.post(reverse('messages_private',args=[self.dev.pk]), {'body':'copy','resend_message':self.message.pk})
        self.assertEqual(response.status_code, 404)

    def test_reedit_keeps_attachment_and_reference_with_current_permissions(self):
        with scratch_dir('message-actions') as directory, override_settings(MEDIA_ROOT=directory):
            response = self.client.post(self.room, {'references':json.dumps(['task:'+str(self.child.pk)]),
                'attachments':SimpleUploadedFile('note.txt', b'original')}, HTTP_ACCEPT='application/json')
            original = ChatMessage.objects.get(pk=response.json()['message']['id'])
            url = reverse('message_action',args=[original.pk])
            file = original.attachments.get()
            self.client.post(url, {'action':'withdraw'})
            self.assertEqual(self.client.get(reverse('attachment_download',args=[file.pk])).status_code, 403)
            draft = self.client.post(url, {'action':'draft'}).json()['draft']
            self.assertEqual(draft['attachments'], ['note.txt'])
            self.assertEqual(draft['references'][0]['key'], 'task:'+str(self.child.pk))
            result = self.client.post(self.room, {'resend_message':original.pk,'references':'[]'}, HTTP_ACCEPT='application/json')
            self.assertEqual(result.status_code, 201)
            new = ChatMessage.objects.get(pk=result.json()['message']['id'])
            self.assertNotEqual(new.pk, original.pk)
            self.assertEqual(new.attachments.get().file.name, file.file.name)
            download = self.client.get(reverse('attachment_download',args=[new.attachments.get().pk]))
            self.assertEqual(download.status_code, 200)
            download.close()

    def test_agent_excludes_deleted_withdrawn_and_nonparticipant_messages(self):
        self.assertTrue(agent.available(self.dev,'message').filter(pk=self.message.pk).exists())
        self.assertFalse(agent.available(self.outsider,'message').filter(pk=self.message.pk).exists())
        self.client.post(self.url, {'action':'withdraw'})
        self.assertFalse(agent.available(self.dev,'message').filter(pk=self.message.pk).exists())
        public = ChatMessage.objects.create(room='developers',author=self.owner,body='hidden')
        public.hidden_by.add(self.dev)
        self.assertFalse(agent.available(self.dev,'message').filter(pk=public.pk).exists())

    def test_csrf_and_post_only_actions(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        protected = Client(enforce_csrf_checks=True)
        protected.force_login(self.dev)
        self.assertEqual(protected.post(self.url, {'action':'withdraw'}).status_code, 403)

    def test_guest_cannot_access_messages(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.room).status_code, 302)
        self.assertEqual(self.client.post(self.url, {'action':'withdraw'}).status_code, 302)

    def test_email_index_blocks_case_variations_even_for_direct_updates(self):
        self.dev.email = 'unique@example.com'
        self.dev.save(update_fields=['email'])
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.filter(pk=self.owner.pk).update(email=' UNIQUE@EXAMPLE.COM ')
