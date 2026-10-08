import json
import re
from unittest.mock import patch
from django.contrib.auth.models import User, Permission
from django.test import TestCase, override_settings
from django.urls import reverse
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from .models import Workspace, Team, TeamMembership, Project, MemberProfile, Friendship, ChatGroup, GroupMember, PersonalMessage, TeamOpening, TeamApplication, Invite
from .tenancy import scope
from .admission import create_team, join_from_invitation


@override_settings(WORKBENCH_OPEN_REGISTRATION=True,EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class WorkspaceV3Tests(TestCase):
    def setUp(self):
        cache.clear()
        with scope(None,http=True):
            self.a=User.objects.create_user('person_a','a@example.com','private-v3-Password7')
            self.b=User.objects.create_user('person_b','b@example.com','private-v3-Password7')
            self.root=User.objects.create_superuser('platform_root','root@example.com','private-v3-Password7')
            for user in [self.a,self.b,self.root]:MemberProfile.objects.create(user=user)
        self.sa=Workspace.objects.create(kind='personal',owner=self.a)
        self.sb=Workspace.objects.create(kind='personal',owner=self.b)
        self.client.force_login(self.a)

    def test_account_pages_work_without_team_but_api_requires_team(self):
        for name in ['workspace_home','dashboard','experiments','me_home','ai_assistant','messages_social']:
            self.assertEqual(self.client.get(reverse(name)).status_code,200,name)
        self.assertRedirects(self.client.get(reverse('teams')),reverse('messages_teams'))
        self.assertRedirects(self.client.get(reverse('me_ledger')),reverse('me_home'))
        page=self.client.get(reverse('api_manage'));self.assertEqual(page.status_code,200);self.assertFalse(page.context['can_manage_api']);self.assertNotContains(page,'name="key_env"')
        self.assertRedirects(self.client.get(reverse('finance_list')),reverse('me_ledger'),fetch_redirect_response=False)
        self.assertContains(self.client.get(reverse('messages_social')),'communication-sidebar')
        data=self.client.get(reverse('desktop_api',args=['status'])).json()
        self.assertTrue(data['needsTeam']);self.assertEqual(data['spaceKind'],'personal')

    def test_personal_scope_isolation_and_links(self):
        with scope(self.sa):p=Project.objects.create(name='private A',owner=self.a,created_by=self.a)
        with scope(self.sb):Project.objects.create(name='private B',owner=self.b,created_by=self.b)
        response=self.client.get(reverse('dashboard'))
        self.assertContains(response,'private A');self.assertNotContains(response,'private B')
        self.client.force_login(self.b)
        self.assertEqual(self.client.get(reverse('project_detail',args=[p.pk])).status_code,404)
        with scope(self.sb):
            with self.assertRaises(PermissionDenied):p.save()

    def test_personal_pool_cannot_read_host_environment_keys(self):
        from aihub.forms import ProviderForm
        with scope(self.sa):
            form=ProviderForm({'name':'test','protocol':'openai','base_url':'https://api.example.com/v1','key_env':'OPENAI_API_KEY','enabled':'on'})
            self.assertFalse(form.is_valid());self.assertIn('key_env',form.errors)

    def test_create_team_without_invite_and_switch_both_ways(self):
        response=self.client.post(reverse('team_create'),{'name':'公账户'})
        self.assertEqual(response.status_code,302)
        team=Team.objects.get(owner=self.a)
        self.assertEqual(TeamMembership.objects.get(team=team,user=self.a).role,'owner')
        self.client.post(reverse('team_switch'),{'team':'personal'})
        self.assertEqual(self.client.get(reverse('desktop_api',args=['status'])).json()['spaceKind'],'personal')
        self.client.post(reverse('team_switch'),{'team':str(team.pk)})
        self.assertEqual(self.client.get(reverse('desktop_api',args=['status'])).json()['teamId'],team.pk)
        self.assertFalse(self.a.has_perm('core.manage_platform_accounts'))

    def test_mailbox_verification_required_for_registration(self):
        data={'username':'email_user','nickname':'昵称','email':'new@example.com','password1':'private-v3-Password7','password2':'private-v3-Password7'}
        self.client.logout()
        self.assertEqual(self.client.post(reverse('account_register'),data).status_code,200)
        self.assertFalse(User.objects.filter(username='email_user').exists())
        with patch('core.registration_email.send_mail') as mail:
            self.client.post(reverse('account_register'),{'action':'send_code','email':data['email']})
        data['email_code']=re.search(r'\d{6}',mail.call_args.args[1]).group()
        self.assertEqual(self.client.post(reverse('account_register'),data).status_code,302)
        user=User.objects.get(username='email_user')
        self.assertFalse(user.team_memberships.exists());self.assertFalse(user.is_staff)

    def test_ordinary_group_and_member_invitation(self):
        Friendship.objects.create(first=self.a,second=self.b)
        response=self.client.post(reverse('group_create'),{'kind':'personal','name':'好友群','members':[str(self.b.pk)]})
        self.assertEqual(response.status_code,302)
        group=ChatGroup.objects.get(owner=self.a)
        self.assertIsNone(group.team_id)
        self.client.force_login(self.b)
        self.assertEqual(self.client.get(reverse('group_chat',args=[group.pk])).status_code,200)
        self.assertEqual(self.client.post(reverse('group_chat',args=[group.pk]),{'body':'hello'},HTTP_ACCEPT='application/json').status_code,200)
        self.assertEqual(self.client.post(reverse('group_manage',args=[group.pk]),{'action':'rename','name':'bad'}).status_code,403)

    def test_friend_chat_navigation_quote_and_withdraw(self):
        Friendship.objects.create(first=self.a,second=self.b)
        url=reverse('personal_chat',args=[self.b.pk])
        response=self.client.get(url);self.assertContains(response,'communication-sidebar');self.assertContains(response,'composer-tools');self.assertContains(response,'data-thread-send')
        self.client.post(url,{'body':'first'},HTTP_ACCEPT='application/json')
        original=PersonalMessage.objects.get(sender=self.a)
        self.client.post(url,{'body':'quote','quoted_message':original.pk},HTTP_ACCEPT='application/json')
        self.assertEqual(PersonalMessage.objects.latest('pk').quote['body'],'first')
        response=self.client.post(reverse('personal_message_action',args=[self.b.pk,original.pk]),{'action':'withdraw'})
        self.assertEqual(response.status_code,200);original.refresh_from_db();self.assertIsNotNone(original.withdrawn_at)

    def test_removed_member_rejoins_without_old_authority(self):
        with scope(None,http=True):team=create_team(self.a,'org')
        TeamMembership.objects.create(team=team,user=self.b,permissions=['finance'])
        TeamMembership.objects.filter(team=team,user=self.b).update(active=False,deleted_at=__import__('django.utils.timezone',fromlist=['now']).now())
        with scope(team):
            invite,code=Invite.issue(self.a)
            join_from_invitation(self.b,code)
        member=TeamMembership.objects.get(team=team,user=self.b)
        self.assertTrue(member.active);self.assertIsNone(member.deleted_at);self.assertEqual(member.permissions,[])

    def test_repeat_application_and_manager_dot(self):
        team=create_team(self.a,'org');team.listed=True;team.save()
        opening=TeamOpening.objects.create(team=team,title='join',description='welcome')
        item=TeamApplication.objects.create(opening=opening,applicant=self.b,state='joined',resume='old')
        self.client.force_login(self.b)
        self.client.post(reverse('team_apply',args=[opening.pk]),{'resume':'again'})
        item.refresh_from_db();self.assertEqual(item.state,'pending')
        self.client.force_login(self.a)
        response=self.client.get(reverse('messages_teams'))
        self.assertContains(response,'加入申请');self.assertContains(response,'data-team-application-dot')
        self.assertFalse(response.context['is_messages']);self.assertTrue(response.context['communication_management'])

    def test_self_close_keeps_organization_records(self):
        team=create_team(self.b,'org')
        TeamMembership.objects.create(team=team,user=self.a)
        with scope(team):project=Project.objects.create(name='org survives',owner=self.b,created_by=self.b)
        response=self.client.post(reverse('account_close'),{'password':'private-v3-Password7','confirm':'注销'})
        self.assertEqual(response.status_code,302)
        self.a.refresh_from_db();self.assertFalse(self.a.is_active);self.assertEqual(self.a.member_profile.nickname,'已注销用户')
        self.assertTrue(Project.all_objects.filter(pk=project.pk).exists())

    def test_owner_must_handoff_before_self_close(self):
        create_team(self.a,'org')
        response=self.client.post(reverse('account_close'),{'password':'private-v3-Password7','confirm':'注销'})
        self.assertEqual(response.status_code,200);self.a.refresh_from_db();self.assertTrue(self.a.is_active)

    def test_platform_ban_does_not_give_private_access_and_unban_invalidates_session(self):
        session=self.client.session;session['account-security-version']=0;session.save()
        from django.test import Client
        admin=Client();admin.force_login(self.root)
        admin.post(reverse('platform_accounts'),{'user':self.a.pk,'action':'ban','reason':'test'})
        admin.post(reverse('platform_accounts'),{'user':self.a.pk,'action':'unban','reason':'test'})
        self.assertEqual(self.client.get(reverse('workspace_home')).status_code,302)
        self.assertFalse(TeamMembership.objects.filter(user=self.root).exists())
