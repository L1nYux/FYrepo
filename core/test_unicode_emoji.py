"""Standard emoji remain Unicode text across discussion surfaces."""
import os
from pathlib import Path

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import (Comment, DocumentComment, DocumentVersion, Friendship,
                     MemberProfile, PersonalMessage, Project, SharedDocument, Workspace)
from .tenancy import scope


class UnicodeEmojiTests(TestCase):
    text = '😁😂😄👿😉😊 👍🏽 👩‍🔬 ❤️'

    def setUp(self):
        with scope(None, http=True):
            self.person = User.objects.create_user('emoji-person')
            self.peer = User.objects.create_user('emoji-peer')
            MemberProfile.objects.create(user=self.person)
            MemberProfile.objects.create(user=self.peer)
        self.space = Workspace.objects.create(kind='personal', owner=self.person)
        Workspace.objects.create(kind='personal', owner=self.peer)
        Friendship.objects.create(first=self.person, second=self.peer)
        self.client.force_login(self.person)

    def test_private_chat_keeps_standard_emoji(self):
        response = self.client.post(reverse('personal_chat', args=[self.peer.pk]),
                                    {'body': self.text}, HTTP_ACCEPT='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(PersonalMessage.objects.get(pk=response.json()['messages'][-1]['id']).body, self.text)

    def test_project_comment_keeps_standard_emoji(self):
        with scope(self.space):
            project = Project.objects.create(name='表情留言', owner=self.person, created_by=self.person)
        response = self.client.post(reverse('project_comment', args=[project.pk]), {'kind': 'note', 'body': self.text})
        self.assertEqual(response.status_code, 302)
        with scope(self.space):
            self.assertEqual(Comment.objects.get(project=project).body, self.text)
        self.assertContains(self.client.get(reverse('project_detail', args=[project.pk])), self.text)

    def test_document_comment_keeps_standard_emoji_and_exposes_picker_assets(self):
        document = SharedDocument.objects.create(workspace=self.space, created_by=self.person, title='科研讨论')
        version = DocumentVersion.objects.create(document=document, number=1, created_by=self.person,
                                                 approved_by=self.person, content={'type': 'doc', 'content': []})
        document.current = version
        document.save(update_fields=['current'])
        response = self.client.post(reverse('document_comment', args=[document.pk]),
                                    {'body': self.text, 'version': version.pk})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(DocumentComment.objects.get(document=document).body, self.text)
        response = self.client.get(reverse('document_detail', args=[document.pk]))
        self.assertContains(response, self.text)
        self.assertContains(response, 'core/comment-emoji.js')
        if os.environ.get('WORKBENCH_CAPTURE_UI'):
            folder = Path(os.environ['WORKBENCH_CAPTURE_UI'])
            folder.mkdir(parents=True, exist_ok=True)
            (folder / 'unicode-document.html').write_bytes(response.content)
