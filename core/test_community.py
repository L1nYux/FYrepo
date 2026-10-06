import json
from django.contrib.auth.models import User, Permission
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from .models import (Team, TeamMembership, TeamCreationInvite, Invite, TeamOpening, TeamApplication,
    FriendRequest, Friendship, PersonalMessage, ChatGroup, GroupMember, GroupMessage)
from .tenancy import scope
from .admission import create_from_invitation, join_from_invitation


class CommunityTests(TestCase):
    def setUp(self):
        cache.clear()
        with scope(None,http=True):
            self.owner=User.objects.create_user('org-owner',password='test-community-Q9-only')
            self.worker=User.objects.create_user('org-worker')
            self.outside=User.objects.create_user('outside')
            self.root=User.objects.create_superuser('software-admin')
        self.team=Team.objects.create(name='原团队测试',owner=self.owner,member_limit=3)
        TeamMembership.objects.create(team=self.team,user=self.owner,role='owner')
        self.membership=TeamMembership.objects.create(team=self.team,user=self.worker,role='member')
        self.client.force_login(self.owner)
        session=self.client.session;session['workbench-team']=self.team.pk;session.save()

    def register(self,code='',team_name='',username='new-account'):
        self.client.logout()
        from .testing_registration import verified_post
        post=(lambda url,data:verified_post(self.client,url,data)) if code else self.client.post
        return post(reverse('account_register'),{'username':username,'email':username+'@example.com',
            'password1':'community-registration-Q29-only','password2':'community-registration-Q29-only','invite_code':code,'team_name':team_name})

    def test_registration_closed_on_both_web_entry_points_and_desktop(self):
        result=self.register()
        self.assertEqual(result.status_code,200);self.assertFalse(User.objects.filter(username='new-account').exists())
        response=self.client.post(reverse('desktop_api',args=['register']),json.dumps({'username':'new-desktop','email':'desktop@example.com',
            'password':'community-registration-Q29-only','passwordConfirm':'community-registration-Q29-only'}),content_type='application/json')
        self.assertEqual(response.status_code,400);self.assertFalse(User.objects.filter(username='new-desktop').exists())
        response=self.client.post(reverse('register'),{'username':'new-legacy','email':'legacy@example.com',
            'password1':'community-registration-Q29-only','password2':'community-registration-Q29-only'})
        self.assertEqual(response.status_code,200);self.assertFalse(User.objects.filter(username='new-legacy').exists())

    def test_creation_invite_registration_sets_limit_and_owner_without_software_permissions(self):
        invite,code=TeamCreationInvite.issue(self.root,7)
        self.assertEqual(self.register(code,'新的团队').status_code,302)
        user=User.objects.get(username='new-account');team=Team.objects.get(owner=user)
        self.assertEqual(team.member_limit,7);self.assertEqual(TeamMembership.objects.get(user=user).role,'owner')
        self.assertFalse(user.is_staff or user.is_superuser or user.has_perm('core.manage_team_admission'))
        invite.refresh_from_db();self.assertEqual(invite.created_team_id,team.pk)
        with self.assertRaises(ValidationError):create_from_invitation(self.outside,code,'重复团队')

    def test_missing_team_name_rolls_back_account_and_invitation(self):
        invite,code=TeamCreationInvite.issue(self.root,7)
        self.assertEqual(self.register(code).status_code,200)
        self.assertFalse(User.objects.filter(username='new-account').exists());invite.refresh_from_db();self.assertIsNone(invite.used_at)

    def test_member_invitation_registration_has_only_current_team_membership(self):
        with scope(self.team):invite,code=Invite.issue(self.owner)
        self.assertEqual(self.register(code).status_code,302)
        user=User.objects.get(username='new-account')
        self.assertEqual(list(TeamMembership.objects.filter(user=user).values_list('team_id','role')),[(self.team.pk,'member')])

    def test_capacity_prevents_join_without_consuming_invite_or_creating_account(self):
        self.team.member_limit=2;self.team.save()
        with scope(self.team):invite,code=Invite.issue(self.owner)
        self.assertEqual(self.register(code).status_code,200)
        self.assertIsNone(Invite.all_objects.get(pk=invite.pk).used_at)
        self.assertFalse(User.objects.filter(username='new-account').exists())
        with self.assertRaises(ValidationError):join_from_invitation(self.outside,code)

    def test_existing_account_can_own_multiple_teams_via_separate_invitations(self):
        for name in ('第二团队','第三团队'):
            invite,code=TeamCreationInvite.issue(self.root,5)
            create_from_invitation(self.owner,code,name)
        self.assertEqual(Team.objects.filter(owner=self.owner).count(),3)

    def test_promoting_suspended_member_respects_capacity(self):
        self.membership.active=False;self.membership.save()
        self.team.member_limit=1;self.team.save()
        response=self.client.post(reverse('members'),{'id':self.worker.pk,'action':'promote'})
        self.assertEqual(response.status_code,302)
        self.membership.refresh_from_db()
        self.assertFalse(self.membership.active);self.assertEqual(self.membership.role,'member')

    def test_malformed_management_ids_are_rejected(self):
        self.assertEqual(self.client.post(reverse('recruitment_manage'),{'action':'close','opening':'oops'}).status_code,403)
        self.assertEqual(self.client.post(reverse('team_application_review'),{'action':'accept','application':'oops'}).status_code,403)
        self.client.force_login(self.root)
        self.assertEqual(self.client.post(reverse('platform'),{'action':'revoke_invite','invite':'oops'}).status_code,403)

    def test_platform_delegation_is_separate_from_team_owner(self):
        self.assertEqual(self.client.post(reverse('platform'),{'action':'create_invite','member_limit':5}).status_code,403)
        permission=Permission.objects.get(codename='manage_team_admission')
        self.worker.user_permissions.add(permission);self.client.force_login(self.worker)
        self.assertEqual(self.client.post(reverse('platform'),{'action':'create_invite','member_limit':5}).status_code,200)
        self.assertFalse(self.worker.is_superuser)
        self.assertEqual(self.client.get('/admin/auth/user/').status_code,403)

    def test_owner_sets_team_local_position_and_limited_capabilities(self):
        response=self.client.post(reverse('team_member_permissions',args=[self.membership.pk]),{'position':'运维','permissions':['announcements','recruitment']})
        self.assertEqual(response.status_code,302);self.membership.refresh_from_db();self.assertEqual(self.membership.position,'运维')
        self.client.force_login(self.worker)
        self.assertEqual(self.client.get(reverse('announcement_new')).status_code,200)
        self.assertEqual(self.client.get(reverse('recruitment_manage')).status_code,200)
        self.assertEqual(self.client.get(reverse('invites')).status_code,403)
        self.assertEqual(self.client.get(reverse('platform')).status_code,403)
        self.assertEqual(self.client.post(reverse('team_member_permissions',args=[self.membership.pk]),{'permissions':['invitations']}).status_code,403)

    def test_unlisted_teams_and_private_data_are_not_in_square(self):
        self.client.force_login(self.outside)
        self.assertNotContains(self.client.get(reverse('team_square')),self.team.name)
        self.assertEqual(self.client.get(reverse('team_listing',args=[self.team.pk])).status_code,404)
        Team.objects.filter(pk=self.team.pk).update(listed=True,introduction='公开介绍')
        self.assertContains(self.client.get(reverse('team_square')),self.team.name)
        self.assertNotContains(self.client.get(reverse('team_listing',args=[self.team.pk])),'API Key')

    def prepare_application(self):
        Team.objects.filter(pk=self.team.pk).update(listed=True)
        opening=TeamOpening.objects.create(team=self.team,title='运维',description='维护工作台')
        self.client.force_login(self.outside)
        self.assertEqual(self.client.post(reverse('team_apply',args=[opening.pk]),{'resume':'私有简历内容','note':'想加入'}).status_code,302)
        return TeamApplication.objects.get(opening=opening)

    def test_application_only_applicant_and_authorized_reviewers_can_read(self):
        item=self.prepare_application()
        self.assertContains(self.client.get(reverse('my_applications')),'私有简历内容')
        self.client.force_login(self.worker)
        self.assertNotContains(self.client.get(reverse('my_applications')),'私有简历内容')
        self.assertEqual(self.client.get(reverse('team_application_review')).status_code,403)
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(reverse('team_application_review')),'私有简历内容')

    def test_acceptance_requires_applicant_confirmation_and_capacity(self):
        item=self.prepare_application();self.client.force_login(self.owner)
        response=self.client.post(reverse('team_application_review'),{'application':item.pk,'action':'accept'})
        self.assertEqual(response.status_code,200);item.refresh_from_db()
        self.assertFalse(TeamMembership.objects.filter(team=self.team,user=self.outside).exists())
        self.client.force_login(self.worker)
        self.assertEqual(self.client.post(reverse('team_application_action',args=[item.pk]),{'action':'join'}).status_code,404)
        Team.objects.filter(pk=self.team.pk).update(member_limit=2)
        self.client.force_login(self.outside)
        self.client.post(reverse('team_application_action',args=[item.pk]),{'action':'join'})
        self.assertFalse(TeamMembership.objects.filter(team=self.team,user=self.outside).exists())
        Team.objects.filter(pk=self.team.pk).update(member_limit=3)
        self.client.post(reverse('team_application_action',args=[item.pk]),{'action':'join'})
        item.refresh_from_db();self.assertEqual(item.state,'joined')
        self.assertTrue(TeamMembership.objects.filter(team=self.team,user=self.outside).exists())

    def test_colleagues_can_chat_without_becoming_friends(self):
        self.assertEqual(self.client.post(reverse('personal_chat',args=[self.worker.pk]),{'body':'同事消息'}).status_code,302)
        self.assertFalse(Friendship.objects.exists())
        self.assertEqual(self.client.get(reverse('personal_chat',args=[self.outside.pk])).status_code,404)

    def test_cross_team_messages_require_accepted_friend_request(self):
        self.client.post(reverse('request_friend'),{'username':self.outside.username,'note':'一起交流'})
        item=FriendRequest.objects.get(sender=self.owner,recipient=self.outside)
        self.assertEqual(self.client.post(reverse('friend_action',args=[item.pk]),{'action':'accept'}).status_code,404)
        self.client.force_login(self.outside)
        self.client.post(reverse('friend_action',args=[item.pk]),{'action':'accept'})
        self.assertEqual(self.client.post(reverse('personal_chat',args=[self.owner.pk]),{'body':'好友消息'}).status_code,302)
        self.assertEqual(PersonalMessage.objects.count(),1)
        self.client.force_login(self.worker)
        self.assertEqual(self.client.get(reverse('personal_chat',args=[self.outside.pk])).status_code,404)

    def test_friendship_survives_team_departure(self):
        first,second=sorted([self.owner.pk,self.worker.pk]);Friendship.objects.create(first_id=first,second_id=second)
        self.membership.active=False;self.membership.save()
        self.assertEqual(self.client.post(reverse('personal_chat',args=[self.worker.pk]),{'body':'离职后好友'}).status_code,302)

    def test_team_group_requires_group_membership_and_live_team_qualification(self):
        response=self.client.post(reverse('group_create'),{'name':'项目群','members':[self.worker.pk]})
        self.assertEqual(response.status_code,302);group=ChatGroup.objects.get(owner=self.owner)
        self.client.force_login(self.worker)
        self.assertEqual(self.client.post(reverse('group_chat',args=[group.pk]),{'body':'群消息'}).status_code,302)
        self.assertEqual(GroupMessage.objects.count(),1)
        self.client.force_login(self.root)
        self.assertEqual(self.client.get(reverse('group_chat',args=[group.pk])).status_code,403)
        self.client.force_login(self.worker);self.membership.active=False;self.membership.save()
        self.assertEqual(self.client.get(reverse('group_chat',args=[group.pk])).status_code,403)

    def test_group_cannot_include_other_team_users(self):
        self.assertEqual(self.client.post(reverse('group_create'),{'name':'越权群','members':[self.outside.pk]}).status_code,403)
        self.assertFalse(ChatGroup.objects.exists())

    def test_group_admin_cannot_demote_other_admin_by_adding_again(self):
        TeamMembership.objects.create(team=self.team,user=self.outside,role='member')
        group=ChatGroup.objects.create(team=self.team,owner=self.owner,name='权限检查群')
        for user in (self.owner,self.worker,self.outside):GroupMember.objects.create(group=group,user=user,admin=True)
        self.client.force_login(self.worker)
        response=self.client.post(reverse('group_manage',args=[group.pk]),{'action':'add','user':self.outside.pk})
        self.assertEqual(response.status_code,403)
        self.assertTrue(GroupMember.objects.get(group=group,user=self.outside).admin)

    def test_home_has_team_square_and_separate_management_entries(self):
        result=self.client.get(reverse('workspace_home'))
        self.assertContains(result,'团队广场');self.assertContains(result,'团队管理')
        self.assertNotContains(result,'href="/platform/"')

    def test_current_community_pages_render_and_capture_ui_contract(self):
        import os
        from pathlib import Path
        Team.objects.filter(pk=self.team.pk).update(listed=True,introduction='一起研究和开发',research_area='软件与科研')
        TeamOpening.objects.create(team=self.team,title='运维伙伴',description='维护服务器、发布公告')
        first,second=sorted([self.owner.pk,self.outside.pk]);Friendship.objects.create(first_id=first,second_id=second)
        PersonalMessage.objects.create(sender=self.outside,recipient=self.owner,body='你好，欢迎交流')
        pages=[('team_square','community-square.html',[]),('recruitment_manage','community-manage.html',[]),
            ('applicant_resume','community-resume.html',[]),('messages_social','community-social.html',[]),
            ('personal_chat','community-thread.html',[self.outside.pk]),('team_manage','community-team-permissions.html',[])]
        directory=os.environ.get('WORKBENCH_CAPTURE_UI')
        for name,file,args in pages:
            response=self.client.get(reverse(name,args=args));self.assertEqual(response.status_code,200,name)
            if name in ('messages_social','personal_chat'):
                self.assertEqual(response.context['shell_section'],'消息')
                self.assertTrue(response.context['is_messages'])
            if directory:
                folder=Path(directory);folder.mkdir(parents=True,exist_ok=True);(folder/file).write_bytes(response.content)
