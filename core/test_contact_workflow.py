"""Acceptance of account workflows without implicit team creation."""
import os
from pathlib import Path
from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from .models import Team, TeamMembership, Friendship, ChatGroup, GroupMember, Workspace
from .tenancy import scope
from .templatetags.avatars import conversation_date


class ContactWorkflowAcceptance(TestCase):
    def setUp(self):
        with scope(None, http=True):
            self.owner = User.objects.create_user('workflow-owner')
            self.friend = User.objects.create_user('workflow-friend')
            self.stranger = User.objects.create_user('workflow-stranger')
        Friendship.objects.create(first=self.owner, second=self.friend)
        self.client.force_login(self.owner)

    def capture(self, name, response):
        folder = os.environ.get('WORKBENCH_CAPTURE_UI')
        if folder:
            Path(folder).mkdir(parents=True, exist_ok=True)
            Path(folder, name+'.html').write_bytes(response.content)

    def test_independent_account_pages_without_a_team(self):
        for view in ('create-group', 'existing-groups', 'add-friend', 'my-qr', 'scan'):
            result = self.client.get('/app/pages/', {'view':view})
            self.assertEqual(result.status_code, 200, view)
            self.assertContains(result, 'data-contact-workflow="'+view+'"')
            self.assertNotContains(result, 'data-contact-add-dialog')
            self.capture('workflow-'+view, result)
        for address in ('/messages/social/', '/me/', '/workspace/', '/assistant/', '/messages/notices/'):
            result = self.client.get(address)
            self.assertEqual(result.status_code, 200, address)
            self.capture('account-'+address.strip('/').replace('/','-'), result)
        self.assertFalse(TeamMembership.objects.filter(user=self.owner).exists())
        self.assertFalse(Team.objects.filter(owner=self.owner).exists())
        self.assertEqual(Workspace.objects.get(owner=self.owner).kind,'personal')

    def test_group_picker_name_defaults_and_authorization(self):
        from django.urls import reverse
        result=self.client.post(reverse('group_create'), {'kind':'personal','picker':'1','members':[self.friend.pk]})
        self.assertEqual(result.status_code,302)
        group=ChatGroup.objects.get(owner=self.owner)
        self.assertTrue(group.name)
        self.assertEqual(set(GroupMember.objects.filter(group=group).values_list('user_id',flat=True)),{self.owner.pk,self.friend.pk})
        self.assertEqual(self.client.get(result.url).status_code,200)
        self.assertFalse(TeamMembership.objects.filter(user=self.owner).exists())
        from django.urls import reverse
        denied=self.client.post(reverse('group_create'), {'kind':'personal','picker':'1','members':[self.stranger.pk]})
        self.assertEqual(denied.status_code,403)
        self.assertEqual(ChatGroup.objects.filter(owner=self.owner).count(),1)
        empty=self.client.post(reverse('group_create'), {'kind':'personal','picker':'1'})
        self.assertEqual(empty.status_code,302)
        self.assertIn('view=create-group',empty.url)

    def test_own_qr_and_search_do_not_grant_membership(self):
        result=self.client.get('/app/pages/',{'view':'my-qr','image':'1'})
        self.assertEqual(result.status_code,200)
        self.assertEqual(result['Content-Type'],'image/svg+xml')
        self.assertIn(b'<svg',result.content)
        folder=os.environ.get('WORKBENCH_CAPTURE_UI')
        if folder: Path(folder,'workflow-my-qr.svg').write_bytes(result.content)
        from django.urls import reverse
        found=self.client.get(reverse('friend_search'),{'q':self.friend.username})
        self.assertEqual(found.status_code,200)
        self.assertEqual(found.json()['friend_state'],'friends')
        self.client.logout()
        self.assertEqual(self.client.get('/app/pages/?view=my-qr&image=1').status_code,302)

    def test_message_list_calendar_labels(self):
        now=timezone.now()
        self.assertEqual(conversation_date(now),timezone.localtime(now).strftime('%H:%M'))
        self.assertEqual(conversation_date(now-timezone.timedelta(days=1)),'昨天')
        self.assertEqual(conversation_date(now-timezone.timedelta(days=2)),'前天')
        old=now-timezone.timedelta(days=400)
        self.assertIn(str(timezone.localtime(old).year),conversation_date(old))
