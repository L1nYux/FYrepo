from .testing_registration import verified_post
import hashlib
import json
from unittest.mock import patch
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from .models import Team, TeamMembership, Project, Task, ChatMessage, Invite, Experiment, Announcement, TeamCreationInvite
from .tenancy import scope, team_users
from . import permissions as perms
from aihub.models import Provider, PoolModel, Allowance, MemberToken, AssistantJob
from aihub.service import allowance, provider_key


class TeamIsolationTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.admin=User.objects.create_user('team-one-admin', is_staff=True, password='test-only-password')
        self.member=User.objects.create_user('shared-member', password='test-only-password')
        with scope(None, http=True):
            self.other=User.objects.create_user('team-two-owner', password='test-only-password')
            self.root=User.objects.create_superuser('platform-only', password='test-only-password')
        self.other_team=Team.objects.create(name='第二团队', owner=self.other)
        TeamMembership.objects.create(team=self.other_team, user=self.other, role='owner')
        TeamMembership.objects.create(team=self.other_team, user=self.member, role='member')
        self.project=Project.objects.create(name='第一团队资料', owner=self.admin, created_by=self.admin)
        with scope(self.other_team):
            self.foreign=Project.objects.create(name='第二团队私有资料', owner=self.other, created_by=self.other)
            self.experiment=Experiment.objects.create(number='DUPLICATE', title='第二团队实验', project=self.foreign, created_by=self.other)
        self.client.force_login(self.admin)

    def select(self, team, user=None):
        if user: self.client.force_login(user)
        session=self.client.session;session['workbench-team']=team.pk;session.save()

    def test_team_admin_has_no_platform_authority(self):
        self.assertEqual(self.client.get(reverse('platform')).status_code,403)
        self.assertEqual(self.client.get('/admin/').status_code,403)
        self.assertTrue(perms.is_admin(self.admin)); self.assertFalse(perms.is_platform_admin(self.admin))

    def test_platform_admin_has_no_implicit_private_team_access(self):
        self.client.force_login(self.root)
        self.assertContains(self.client.get(reverse('platform')),'第二团队')
        self.assertEqual(self.client.get(reverse('project_detail',args=[self.foreign.pk])).status_code,404)
        with scope(self.other_team): self.assertFalse(perms.is_admin(self.root))

    def test_http_detail_mutation_and_chat_do_not_cross_teams(self):
        self.assertEqual(self.client.get(reverse('project_detail',args=[self.foreign.pk])).status_code,404)
        self.assertEqual(self.client.post(reverse('member_delete',args=[self.other.pk]),{'confirm_username':self.other.username}).status_code,404)
        self.assertEqual(self.client.get(reverse('messages_private',args=[self.other.pk])).status_code,404)
        self.assertNotContains(self.client.get(reverse('members')),self.other.username)

    def test_model_queries_foreign_keys_and_m2m_are_scoped(self):
        self.assertEqual(list(Project.objects.values_list('pk',flat=True)),[self.project.pk])
        self.assertNotIn(self.other,team_users())
        with self.assertRaises(ValidationError): Task.objects.create(project=self.foreign,title='wrong',created_by=self.admin)
        with self.assertRaises(ValidationError), transaction.atomic(): self.project.members.add(self.other)
        with self.assertRaises(ValidationError), transaction.atomic(): self.foreign.members.add(self.other)
        with self.assertRaises(PermissionDenied): self.foreign.delete()
        self.assertTrue(Project.all_objects.filter(pk=self.foreign.pk).exists())

    def test_changing_team_on_an_existing_object_is_rejected(self):
        self.foreign.team_id=1
        with self.assertRaises(PermissionDenied): self.foreign.save()
        self.assertEqual(Project.all_objects.get(pk=self.foreign.pk).team_id,self.other_team.pk)

    def test_bulk_writes_cannot_cross_teams(self):
        with self.assertRaises(PermissionDenied): Project.objects.bulk_update([self.foreign],['name'])
        with self.assertRaises(ValidationError): Project.objects.filter(pk=self.project.pk).update(owner=self.other)
        with self.assertRaises(ValidationError): Project.objects.filter(pk=self.project.pk).update(team_id=self.other_team.pk)

    def test_switch_changes_data_and_role_and_invalid_switch_is_rejected(self):
        response=self.client.post(reverse('team_switch'),{'team':self.other_team.pk})
        self.assertEqual(response.status_code,404)
        TeamMembership.objects.create(team=self.other_team,user=self.admin,role='member')
        response=self.client.post(reverse('team_switch'),{'team':self.other_team.pk})
        self.assertEqual(response.status_code,302)
        status=self.client.get(reverse('desktop_api',args=['status'])).json()
        self.assertEqual(status['teamId'],self.other_team.pk);self.assertFalse(status['isAdmin'])
        self.assertContains(self.client.get(reverse('project_detail',args=[self.foreign.pk])),'第二团队私有资料')
        self.assertEqual(self.client.get(reverse('project_detail',args=[self.project.pk])).status_code,200)
        self.assertEqual(self.client.post(reverse('team_switch'),{'team':'bad'}).status_code,302)

    @override_settings(WORKBENCH_OPEN_REGISTRATION=True)
    def test_open_registration_flag_does_not_grant_team_membership(self):
        self.client.logout()
        response=verified_post(self.client,reverse('account_register'),{'username':'independent-new','email':'new@example.com',
            'password1':'independent-Q29-password','password2':'independent-Q29-password'})
        self.assertEqual(response.status_code,302)
        account=User.objects.get(username='independent-new')
        self.assertFalse(TeamMembership.objects.filter(user=account).exists())
        self.assertFalse(self.client.get(reverse('desktop_api',args=['status'])).json()['needsTeam'])
        _invite,code=TeamCreationInvite.issue(self.root,10)
        self.assertEqual(self.client.post(reverse('team_create'),{'name':'新团队','code':code}).status_code,302)
        membership=TeamMembership.objects.get(user=account)
        self.assertEqual(membership.role,'owner')
        with scope(membership.team_id):
            self.assertFalse(Project.objects.exists());self.assertTrue(perms.is_admin(account))

    def test_join_existing_account_and_invite_registration_use_invite_team(self):
        with scope(self.other_team): invite,code=Invite.issue(self.other)
        self.assertEqual(self.client.post(reverse('team_join'),{'code':code}).status_code,302)
        self.assertEqual(TeamMembership.objects.get(user=self.admin,team=self.other_team).role,'member')
        with scope(self.other_team): invite2,code2=Invite.issue(self.other)
        self.client.logout()
        response=verified_post(self.client,reverse('register'),{'username':'invited-other-team','email':'invite@example.com',
            'password1':'independent-Q29-password','password2':'independent-Q29-password','invite_code':code2})
        self.assertEqual(response.status_code,302)
        self.assertEqual(TeamMembership.objects.get(user__username='invited-other-team').team_id,self.other_team.pk)

    def test_suspension_cannot_be_bypassed_with_another_invite(self):
        TeamMembership.objects.filter(user=self.member,team=self.other_team).update(active=False)
        with scope(self.other_team): invite,code=Invite.issue(self.other)
        self.client.force_login(self.member)
        self.assertEqual(self.client.post(reverse('team_join'),{'code':code}).status_code,302)
        with scope(self.other_team): invite.refresh_from_db()
        self.assertIsNone(invite.used_at)
        self.assertFalse(TeamMembership.objects.get(user=self.member,team=self.other_team).active)

    def test_team_management_does_not_change_global_or_other_team_permissions(self):
        self.client.post(reverse('members'),{'id':self.member.pk,'action':'promote'})
        self.member.refresh_from_db();self.assertFalse(self.member.is_staff)
        self.assertEqual(TeamMembership.objects.get(user=self.member,team_id=1).role,'admin')
        self.assertEqual(TeamMembership.objects.get(user=self.member,team=self.other_team).role,'member')
        self.client.post(reverse('members'),{'id':self.member.pk,'action':'deactivate'})
        self.member.refresh_from_db();self.assertTrue(self.member.is_active)
        with scope(self.other_team): self.assertTrue(perms.is_team_member(self.member))

    def test_team_admin_cannot_reset_shared_or_platform_account_password(self):
        old=self.member.password
        result=self.client.post(reverse('member_reset_password',args=[self.member.pk]),{'confirm':'reset'})
        self.assertEqual(result.status_code,403);self.member.refresh_from_db();self.assertEqual(self.member.password,old)

    def test_remove_membership_retains_account_other_team_and_history(self):
        message=ChatMessage.objects.create(author=self.member,recipient=self.admin,room='private',body='历史消息')
        response=self.client.post(reverse('member_delete',args=[self.member.pk]),{'confirm_username':self.member.username})
        self.assertEqual(response.status_code,302)
        self.member.refresh_from_db();self.assertTrue(self.member.is_active)
        self.assertContains(self.client.get(reverse('messages_private',args=[self.member.pk])),'历史消息')
        self.assertEqual(self.client.post(reverse('messages_private',args=[self.member.pk]),{'body':'hello'},HTTP_ACCEPT='application/json').status_code,403)
        with scope(self.other_team): self.assertTrue(perms.is_team_member(self.member))

    def test_transfer_requires_owner_confirmation_and_keeps_one_owner(self):
        self.select(self.other_team,self.other)
        self.assertEqual(self.client.post(reverse('team_transfer'),{'user':self.member.pk,'confirm':'wrong'}).status_code,302)
        self.other_team.refresh_from_db();self.assertEqual(self.other_team.owner_id,self.other.pk)
        self.assertEqual(self.client.post(reverse('team_transfer'),{'user':self.member.pk,'confirm':self.other_team.name}).status_code,302)
        self.other_team.refresh_from_db();self.assertEqual(self.other_team.owner_id,self.member.pk)
        self.assertEqual(TeamMembership.objects.filter(team=self.other_team,role='owner').count(),1)
        self.assertEqual(TeamMembership.objects.get(user=self.other,team=self.other_team).role,'admin')

    def test_team_can_reuse_experiment_number_and_release_version(self):
        Experiment.objects.create(number='DUPLICATE',title='本团队实验',project=self.project,created_by=self.admin)
        Announcement.objects.create(title='v1',release_version='1.0.0')
        with scope(self.other_team): Announcement.objects.create(title='v1',release_version='1.0.0')
        self.assertEqual(Experiment.objects.count(),1);self.assertEqual(Announcement.objects.count(),1)

    def test_allowances_credentials_and_personal_api_key_stay_in_their_team(self):
        one=allowance(self.member);one.extra_balance=5;one.save()
        key='test-only-team-token';token=MemberToken.objects.create(user=self.member,label='key',prefix='test',digest=hashlib.sha256(key.encode()).hexdigest())
        with scope(self.other_team):
            self.assertEqual(allowance(self.member).extra_balance,0)
            provider=Provider.objects.create(name='foreign',base_url='https://example.com/v1',key_env='GLOBAL_PROVIDER_KEY')
            with patch.dict('os.environ',{'GLOBAL_PROVIDER_KEY':'must-not-leak'}):self.assertEqual(provider_key(provider),'')
        with self.assertRaises(PermissionDenied):provider_key(provider)
        self.select(self.other_team,self.member)
        response=self.client.get(reverse('pool_experiments'),HTTP_AUTHORIZATION='Bearer '+key)
        self.assertEqual(response.status_code,200);self.assertNotIn(self.experiment.pk,[row['id'] for row in response.json()['data']])
        TeamMembership.objects.filter(team_id=1,user=self.member).update(active=False)
        self.assertEqual(self.client.get(reverse('pool_experiments'),HTTP_AUTHORIZATION='Bearer '+key).status_code,403)

    def test_discovery_ticket_is_bound_to_team(self):
        from tempfile import TemporaryDirectory
        from django.test import override_settings
        from aihub.pending_discovery import stage, load
        with TemporaryDirectory() as directory, override_settings(DATA_DIR=directory):
            ticket=stage({'user':self.member.pk, 'models':[]})
            self.assertEqual(load(ticket,self.member)['team'],1)
            with scope(self.other_team), self.assertRaises(ValidationError):load(ticket,self.member)

    def test_platform_disable_removes_team_access_without_changing_accounts(self):
        self.client.force_login(self.root)
        self.assertEqual(self.client.post(reverse('platform'),{'team':self.other_team.pk,'action':'disable'}).status_code,302)
        self.select(self.other_team,self.other)
        self.assertFalse(self.client.get(reverse('desktop_api',args=['status'])).json()['needsTeam'])
        self.other.refresh_from_db();self.assertTrue(self.other.is_active)

    def test_background_worker_restores_job_team_before_reading_records(self):
        from contextlib import ExitStack
        from aihub.agent import worker
        with scope(self.other_team):
            provider=Provider.objects.create(name='worker',base_url='https://example.com/v1')
            model=PoolModel.objects.create(provider=provider,model_id='worker')
            job=AssistantJob.objects.create(user=self.other,user_text='你好')
        reply={'text':'你好','tool_calls':[],'status':'success','cost_cny':'0','counts':None}
        def check_tool(user,name,args):
            self.assertEqual(list(Project.objects.values_list('pk',flat=True)),[self.foreign.pk])
            self.assertEqual(user.pk,self.other.pk);return {}
        with ExitStack() as stack:
            for name in ('CAPACITY','connections.close_all','close_old_connections'):stack.enter_context(patch('aihub.agent.'+name))
            stack.enter_context(patch('aihub.agent.run_tool',side_effect=check_tool))
            stack.enter_context(patch('aihub.agent.execute',return_value=reply))
            worker(job.pk,self.other.pk,model.pk,[{'role':'user','content':'你好'}],None)
        self.assertEqual(AssistantJob.all_objects.get(pk=job.pk).state,'done')
        self.assertEqual(list(Project.objects.values_list('pk',flat=True)),[self.project.pk])

    @override_settings(WORKBENCH_OPEN_REGISTRATION=True)
    def test_desktop_open_registration_flag_still_requires_team_creation_invitation(self):
        self.client.logout()
        result=verified_post(self.client,reverse('desktop_api',args=['register']),json.dumps({
            'username':'independent-desktop','email':'desktop@example.com',
            'password':'fixture-desktop-Q5-only','passwordConfirm':'fixture-desktop-Q5-only'}),content_type='application/json')
        self.assertEqual(result.status_code,200)
        self.assertTrue(result.json()['authenticated']);self.assertFalse(result.json()['needsTeam'])
        user=User.objects.get(username='independent-desktop')
        self.assertFalse(TeamMembership.objects.filter(user=user).exists())
        self.assertEqual(self.client.get(reverse('project_detail',args=[self.project.pk])).status_code,404)
        _invite,code=TeamCreationInvite.issue(self.root,10)
        self.client.post(reverse('team_create'),{'name':'桌面新团队','code':code})
        status=self.client.get(reverse('desktop_api',args=['status'])).json()
        self.assertEqual(status['teamName'],'桌面新团队');self.assertTrue(status['isAdmin'])
        self.assertFalse(status['isPlatformAdmin']);self.assertFalse(status['needsTeam'])

    def test_desktop_guest_login_can_create_team_without_private_access(self):
        self.client.logout()
        TeamMembership.objects.filter(user=self.member,team_id=1).update(role='guest')
        result=self.client.post(reverse('desktop_api',args=['login']),json.dumps({
            'username':self.member.username,'password':'test-only-password'}),content_type='application/json')
        self.assertEqual(result.status_code,200)
        # Default to the real membership in the second team instead of the guest team.
        self.assertEqual(result.json()['teamId'],self.other_team.pk)
        self.assertFalse(result.json()['isAdmin'])
        self.client.post(reverse('team_switch'),{'team':1})
        status=self.client.get(reverse('desktop_api',args=['status'])).json()
        self.assertFalse(status['needsTeam']);self.assertEqual(status['spaceKind'],'personal')
        self.assertEqual(self.client.get(reverse('project_detail',args=[self.project.pk])).status_code,404)

    def test_business_form_choices_use_membership_not_global_profile(self):
        from .forms import ProjectForm, CompetitionForm
        with scope(self.other_team):
            self.assertIn(self.other,ProjectForm().fields['owner'].queryset)
            self.assertIn(self.other,CompetitionForm().fields['owner'].queryset)
            self.assertNotIn(self.admin,ProjectForm().fields['owner'].queryset)
        TeamMembership.objects.filter(user=self.member,team_id=1).update(role='guest')
        self.assertNotIn(self.member,ProjectForm().fields['members'].queryset)

    def test_invalid_team_identifiers_are_rejected_without_server_error(self):
        self.client.force_login(self.admin)
        for value in ['abc','9'*500,'²']:
            self.assertEqual(self.client.post(reverse('team_switch'),{'team':value}).status_code,302)
            self.assertEqual(self.client.post(reverse('team_transfer'),{'user':value}).status_code,302)
        self.client.force_login(self.root)
        self.assertEqual(self.client.post(reverse('platform'),{'team':'abc','action':'disable'}).status_code,403)

    def test_team_navigation_fixture_has_only_authorized_management_links(self):
        self.client.force_login(self.admin)
        response=self.client.get(reverse('teams'))
        self.assertNotContains(response,'第二团队')
        self.assertContains(response,'创建团队')
        self.assertNotContains(response,reverse('platform'))
        import os
        from pathlib import Path
        directory=os.environ.get('WORKBENCH_CAPTURE_UI')
        if directory:
            path=Path(directory);path.mkdir(parents=True,exist_ok=True)
            (path/'teams.html').write_bytes(response.content)

    async def test_async_requests_keep_the_selected_team_scope(self):
        from django.test import AsyncClient
        client=AsyncClient()
        await client.aforce_login(self.member)
        session=await client.asession()
        await session.aset('workbench-team',self.other_team.pk)
        await session.asave()
        response=await client.get(reverse('project_detail',args=[self.foreign.pk]))
        self.assertEqual(response.status_code,200)
        response=await client.get(reverse('project_detail',args=[self.project.pk]))
        self.assertEqual(response.status_code,200)
