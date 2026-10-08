from django.test import TestCase
from django.urls import reverse
from .test_community import CommunityTests
from .models import ApplicationRelease, Announcement, Team, TeamMembership, Friendship, PersonalMessage, PersonalThreadRead
from .releases import publish, bundled
from .tenancy import scope


class CommunicationNavigationTests(TestCase):
    setUp=CommunityTests.setUp

    def test_team_pages_are_workbench_pages_and_settings_only_account(self):
        session=self.client.session;session['desktop_client']=True;session.save()
        for name in ['teams','team_manage','recruitment_manage','members','contact_edit','invites']:
            response=self.client.get(reverse(name),follow=True);self.assertEqual(response.status_code,200,name)
            self.assertFalse(response.context['desktop_settings_page'],name)
        self.assertTrue(self.client.get(reverse('profile')).context['desktop_settings_page'])

    def test_team_rename_validates_and_only_changes_current_team(self):
        other=Team.objects.create(name='另一个团队',owner=self.outside,member_limit=40)
        self.client.post(reverse('team_rename'),{'name':'新团队名称'})
        self.team.refresh_from_db();other.refresh_from_db()
        self.assertEqual(self.team.name,'新团队名称');self.assertEqual(self.team.member_limit,3);self.assertEqual(other.name,'另一个团队')
        self.client.post(reverse('team_rename'),{'name':' '*5});self.team.refresh_from_db();self.assertEqual(self.team.name,'新团队名称')
        self.client.force_login(self.worker);self.assertEqual(self.client.post(reverse('team_rename'),{'name':'越权'}).status_code,403)

    def test_global_release_is_single_copy_and_separate_from_team_announcements(self):
        item,_=publish(bundled());other=Team.objects.create(name='另一个团队',owner=self.outside)
        with scope(other):self.assertEqual(publish(bundled())[0].pk,item.pk)
        with scope(self.team):Announcement.objects.create(title='团队通知',body='安排')
        self.assertEqual(ApplicationRelease.objects.count(),1)
        home=self.client.get(reverse('workspace_home'))
        self.assertNotContains(home,'团队通知')
        home=self.client.get(reverse('messages_teams')+'?team='+str(self.team.pk))
        self.assertContains(home,'团队通知');self.assertNotContains(home,'data-release-update')
        self.assertContains(self.client.get(reverse('application_updates')),'data-release-update')
        self.client.force_login(self.outside);self.assertContains(self.client.get(reverse('application_updates')),'data-release-update')

    def test_no_team_has_same_contacts_shell_and_exact_account_search(self):
        self.client.force_login(self.outside)
        response=self.client.get(reverse('messages_social')+'?tab=friends')
        self.assertContains(response,'communication-sidebar');self.assertContains(response,'data-contact-add-open')
        self.assertContains(response,'workbench-shell');self.assertNotContains(response,'public-header')
        found=self.client.get(reverse('friend_search'),{'q':self.worker.username}).json()
        self.assertEqual(found['id'],self.worker.pk)
        self.assertFalse({'email','projects','name','bio'}&set(found))
        self.assertEqual(self.client.get(reverse('friend_search'),{'q':'org-'}).status_code,404)
        self.assertEqual(self.client.get(reverse('personal_chat',args=[self.worker.pk])).status_code,404)

    def test_contact_layout_fixture(self):
        import os
        from pathlib import Path
        Friendship.objects.create(first=self.owner,second=self.outside)
        response=self.client.get(reverse('messages_social')+'?tab=friends')
        self.assertContains(response,'data-contact-id')
        target=os.environ.get('WORKBENCH_CAPTURE_UI')
        if target:Path(target,'community-contacts.html').write_bytes(response.content)

    def test_avatar_friend_request_and_accept_do_not_grant_team_permissions(self):
        self.client.post(reverse('request_friend'),{'username':self.outside.username},HTTP_ACCEPT='application/json')
        self.client.force_login(self.outside)
        from .models import FriendRequest
        item=FriendRequest.objects.get(sender=self.owner,recipient=self.outside)
        card=self.client.get(reverse('member_card',args=[self.owner.pk])).json()
        self.assertEqual(card['friend_state'],'received');self.assertEqual(card['projects'],[])
        self.assertEqual(self.client.post(card['friend_url'],{'action':'accept'},HTTP_ACCEPT='application/json').json()['state'],'friends')
        self.assertContains(self.client.get(reverse('personal_chat',args=[self.owner.pk])),'data-personal-thread')
        self.assertFalse(TeamMembership.objects.filter(user=self.outside,team=self.team).exists())

    def test_personal_unread_respects_permission_and_read_cursor(self):
        message=PersonalMessage.objects.create(sender=self.worker,recipient=self.owner,body='你好')
        self.assertEqual(self.client.get(reverse('messages_unread')).json()['channels']['person:'+str(self.worker.pk)],1)
        self.client.get(reverse('personal_chat',args=[self.worker.pk]))
        self.assertEqual(PersonalThreadRead.objects.get(user=self.owner).last_message_id,message.pk)
        self.assertNotIn('person:'+str(self.worker.pk),self.client.get(reverse('messages_unread')).json()['channels'])
        PersonalMessage.objects.create(sender=self.outside,recipient=self.owner,body='不可见')
        response=self.client.get(reverse('messages_social'))
        self.assertNotContains(response,'不可见')

    def test_browser_hidden_personal_poll_does_not_read_messages(self):
        message=PersonalMessage.objects.create(sender=self.worker,recipient=self.owner,body='保持未读')
        # The UI only polls active visible documents; initial read is monotonic.
        self.client.get(reverse('personal_chat',args=[self.worker.pk]),HTTP_ACCEPT='application/json')
        self.assertEqual(PersonalThreadRead.objects.get(user=self.owner).last_message_id,message.pk)
        self.client.get(reverse('personal_chat',args=[self.worker.pk]),{'after':message.pk},HTTP_ACCEPT='application/json')
        self.assertEqual(PersonalThreadRead.objects.get(user=self.owner).last_message_id,message.pk)
