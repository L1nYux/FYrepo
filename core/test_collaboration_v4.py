"""Account, offer, project, and funding boundaries through actual application routes."""
import json
from decimal import Decimal
from datetime import timedelta
from unittest.mock import patch
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied,ValidationError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from .models import Workspace,Team,TeamMembership,MemberProfile,Project,Task,Comment,Submission,ApplicantProfile,RecruitmentOffer,ProjectCollaborator,TeamOpening,TeamApplication,AccountNotice,ExpenseClaim,UsageReceipt
from .tenancy import scope
from aihub.models import Provider,PoolModel,PriceVersion,Call,AssistantConversation,AssistantJob,Allowance,PointGrant


class CollaborationV4Tests(TestCase):
    def setUp(self):
        with scope(None,http=True):
            self.owner=User.objects.create_user('v4-owner')
            self.person=User.objects.create_user('v4-person')
            self.stranger=User.objects.create_user('v4-stranger')
            for user in (self.owner,self.person,self.stranger):MemberProfile.objects.create(user=user)
        self.personal=Workspace.objects.create(kind='personal',owner=self.person)
        Workspace.objects.create(kind='personal',owner=self.owner)
        self.team=Team.objects.create(name='合作团队',owner=self.owner,listed=True,member_limit=2)
        self.teamspace=Workspace.objects.create(kind='team',team=self.team)
        self.membership=TeamMembership.objects.create(team=self.team,user=self.owner,role='owner')
        ApplicantProfile.objects.create(user=self.person,listed=True,intention='研究协作')
        with scope(self.teamspace):
            self.project=Project.objects.create(name='合作项目',owner=self.owner,created_by=self.owner)
            self.other=Project.objects.create(name='另一个私有项目',owner=self.owner,created_by=self.owner)
        self.client.force_login(self.person)
        session=self.client.session;session['workbench-space']='personal';session.save()

    def offer(self,project=None,**kwargs):
        return RecruitmentOffer.objects.create(team=self.team,recipient=self.person,issued_by=self.owner,project=project,title='研究合作',terms='提交成果，由团队验收。',expires_at=timezone.now()+timedelta(days=7),**kwargs)

    def accept(self,offer):
        return self.client.post(reverse('talent_offer_respond',args=[offer.pk]),{'action':'accept'})

    def test_team_offer_requires_recipient_and_accepts_once(self):
        item=self.offer()
        self.assertFalse(TeamMembership.objects.filter(team=self.team,user=self.person).exists())
        self.client.force_login(self.stranger)
        self.assertEqual(self.accept(item).status_code,403)
        self.client.force_login(self.person)
        self.assertEqual(self.accept(item).status_code,302)
        self.assertEqual(self.accept(item).status_code,302)
        self.assertEqual(TeamMembership.objects.filter(team=self.team,user=self.person).count(),1)
        self.assertEqual(TeamMembership.objects.get(team=self.team,user=self.person).permissions,[])

    def test_capacity_and_revoked_issuer_do_not_admit(self):
        item=self.offer()
        TeamMembership.objects.create(team=self.team,user=self.stranger,role='member')
        self.accept(item);item.refresh_from_db();self.assertEqual(item.state,'pending')
        self.membership.active=False;self.membership.save()
        self.assertEqual(self.accept(item).status_code,403)
        self.assertFalse(TeamMembership.objects.filter(team=self.team,user=self.person).exists())

    def test_project_offer_does_not_grant_team_pool_or_other_projects(self):
        item=self.offer(project=self.project)
        self.assertEqual(self.accept(item).status_code,302)
        self.assertFalse(TeamMembership.objects.filter(team=self.team,user=self.person).exists())
        self.assertContains(self.client.get(reverse('project_detail',args=[self.project.pk])),'合作项目')
        self.assertEqual(self.client.get(reverse('project_detail',args=[self.other.pk])).status_code,404)
        self.assertEqual(self.client.get(reverse('finance_list')+'?ownership='+str(self.teamspace.pk)).status_code,403)
        self.assertEqual(self.client.get(reverse('api_catalog')+'?funding='+str(self.teamspace.pk)).status_code,403)
        response=self.client.post(reverse('project_comment',args=[self.project.pk]),{'body':'一起协作 🧪','kind':'idea'})
        self.assertEqual(response.status_code,302)
        self.assertTrue(Comment.all_objects.filter(project=self.project,author=self.person).exists())
        response=self.client.post(reverse('project_submit',args=[self.project.pk]),{'summary':'可验收成果'})
        self.assertEqual(response.status_code,302)
        self.assertTrue(Submission.all_objects.filter(project=self.project,author=self.person).exists())
        ProjectCollaborator.objects.filter(project=self.project,user=self.person).update(active=False)
        self.assertEqual(self.client.get(reverse('project_detail',args=[self.project.pk])).status_code,404)

    def test_project_owner_can_revoke_with_notification(self):
        self.accept(self.offer(project=self.project))
        self.client.force_login(self.owner)
        result=self.client.post(reverse('project_cooperation_revoke',args=[self.project.pk]),{'user':self.person.pk})
        self.assertEqual(result.status_code,302)
        self.assertFalse(ProjectCollaborator.objects.get(project=self.project,user=self.person).active)
        self.assertTrue(AccountNotice.objects.filter(user=self.person,title='项目合作授权已结束').exists())

    def test_application_approval_admits_without_second_confirmation(self):
        with scope(self.teamspace):
            opening=TeamOpening.objects.create(team=self.team,title='研究岗位',description='研究工作',planned_headcount=1)
        application=TeamApplication.objects.create(opening=opening,applicant=self.person,resume='自愿申请')
        self.client.force_login(self.owner)
        result=self.client.post(reverse('messages_team_review')+'?team='+str(self.team.pk),{'application':application.pk,'action':'accept','review_note':'欢迎'})
        self.assertEqual(result.status_code,200)
        application.refresh_from_db();self.assertEqual(application.state,'joined')
        self.assertTrue(TeamMembership.objects.filter(team=self.team,user=self.person,active=True).exists())
        self.assertIsNone(application.invite_id)

    def test_opt_in_and_private_recruitment(self):
        response=self.client.get(reverse('talent_market'));self.assertContains(response,'研究协作')
        ApplicantProfile.objects.filter(user=self.person).update(listed=False)
        self.client.force_login(self.owner)
        self.assertNotContains(self.client.get(reverse('talent_market')),'研究协作')
        self.assertEqual(self.client.get(reverse('talent_detail',args=[self.person.pk])).status_code,404)
        self.team.recruitment_mode='invite';self.team.save()
        with scope(self.teamspace):
            opening=TeamOpening.objects.create(team=self.team,title='只邀请',description='工作')
        self.client.force_login(self.person)
        self.assertEqual(self.client.post(reverse('team_apply',args=[opening.pk]),{'introduction':'申请'}).status_code,404)

    def pool(self,space,user):
        with scope(space):
            provider=Provider.objects.create(name='用量测试',base_url='https://example.com/v1')
            model=PoolModel.objects.create(provider=provider,model_id='test')
            price=PriceVersion.objects.create(model=model,effective_from=timezone.now(),input_rate=1,output_rate=2,cached_rate=1,cache_write_rate=1)
            return model,price

    def test_team_funding_creates_personal_job_and_survives_removal(self):
        member=TeamMembership.objects.create(team=self.team,user=self.person,role='member')
        model,price=self.pool(self.teamspace,self.person)
        with patch('aihub.views.provider_key',return_value='test-key'),patch('aihub.agent.threading.Thread'):
            response=self.client.post(reverse('ai_start'),json.dumps({'model':model.pk,'funding':self.teamspace.pk,'messages':[{'role':'user','content':'私有问题'}]}),content_type='application/json')
        self.assertEqual(response.status_code,202,response.content)
        job=AssistantJob.all_objects.get(pk=response.json()['job'])
        self.assertEqual(job.workspace_id,self.personal.pk);self.assertEqual(job.billing_workspace_id,self.teamspace.pk)
        self.assertEqual(job.conversation.workspace_id,self.personal.pk)
        from aihub.agent import CAPACITY
        CAPACITY.release()
        member.active=False;member.save()
        self.assertEqual(self.client.get(reverse('ai_conversation',args=[job.conversation_id])).status_code,200)
        self.assertEqual(self.client.get(reverse('api_catalog')+'?funding='+str(self.teamspace.pk)).status_code,403)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse('ai_conversation',args=[job.conversation_id])).status_code,404)

    def test_cross_owner_data_tools_do_not_inherit_personal_admin(self):
        from aihub.agent import run_tool,read_record
        from .models import FinanceEntry
        TeamMembership.objects.create(team=self.team,user=self.person,role='member')
        with scope(self.teamspace):
            entry=FinanceEntry.objects.create(kind='income',amount=10,occurred_on=timezone.localdate(),memo='团队财务机密',created_by=self.owner)
        with scope(self.personal):
            self.assertEqual(read_record(self.person,'entry',entry.pk),{'error':'资料已删除或当前账户无权查看。'})
            self.assertIn('description',read_record(self.person,'project',self.project.pk))

    def test_personal_usage_receipt_rejects_duplicate_and_quota_approval_is_idempotent(self):
        from .funding_claims import submit
        TeamMembership.objects.create(team=self.team,user=self.person,role='member')
        model,price=self.pool(self.personal,self.person)
        with scope(self.personal):
            call=Call.objects.create(user=self.person,model=model,price=price,status='success',cost_cny=Decimal('1.20'),budget_month=timezone.localdate().replace(day=1))
        with scope(self.teamspace):
            claim=ExpenseClaim(applicant=self.person,settlement_kind='api_quota',amount=Decimal('1.20'),occurred_on=timezone.localdate(),memo='成果验收后补助')
            submit(claim,[call])
            with self.assertRaises(ValidationError):
                submit(ExpenseClaim(applicant=self.person,amount=1,occurred_on=timezone.localdate(),memo='重复'),[call])
        self.client.force_login(self.owner)
        url=reverse('claim_review',args=[claim.pk])
        self.assertEqual(self.client.post(url,{'decision':'approve','note':'成果合格'}).status_code,302)
        self.assertEqual(self.client.post(url,{'decision':'approve'}).status_code,302)
        with scope(self.teamspace):
            self.assertEqual(Allowance.objects.get(user=self.person).extra_balance,Decimal('1.20'))
            self.assertEqual(PointGrant.objects.filter(user=self.person).count(),1)
        self.assertTrue(AccountNotice.objects.filter(user=self.person,title='经费申请已处理').exists())

    def test_migration_preserves_payer_and_personalizes_legacy_history(self):
        with scope(self.teamspace):
            convo=AssistantConversation.objects.create(user=self.owner,title='旧私有对话')
            job=AssistantJob.objects.create(user=self.owner,conversation=convo,user_text='私有历史')
        from importlib import import_module
        apps=MigrationExecutor(connection).loader.project_state([('aihub','0020_personal_assistant_history')]).apps
        import_module('aihub.migrations.0020_personal_assistant_history').move_private_history(apps,connection.schema_editor())
        job=AssistantJob.all_objects.get(pk=job.pk)
        self.assertEqual(job.workspace.kind,'personal');self.assertEqual(job.workspace.owner_id,self.owner.pk)
        self.assertEqual(job.billing_workspace_id,self.teamspace.pk)
        self.assertEqual(job.creation_order.workspace_id,job.workspace_id)

    def test_running_agent_rechecks_team_pool_before_next_paid_turn(self):
        from aihub.agent import worker,CAPACITY
        member=TeamMembership.objects.create(team=self.team,user=self.person,role='member')
        model,_=self.pool(self.teamspace,self.person)
        model.supports_tools=True
        with scope(self.teamspace):model.save(update_fields=['supports_tools'])
        with scope(self.personal):
            job=AssistantJob.objects.create(user=self.person,user_text='请帮我整理',billing_workspace=self.teamspace)
        def first_turn(*args,**kwargs):
            member.active=False;member.save()
            return {'cost_cny':'.20','status':'success','text':'','reasoning':'','counts':None,'tool_calls':[{'id':'read-1','type':'function','function':{'name':'my_workspace','arguments':'{}'}}]}
        CAPACITY.acquire()
        with patch('aihub.agent.execute',side_effect=first_turn) as execute:
            worker(job.pk,self.person.pk,model.pk,[{'role':'user','content':'请帮我整理'}],None)
        job=AssistantJob.all_objects.get(pk=job.pk)
        self.assertEqual(execute.call_count,1)
        self.assertEqual(job.state,'error')
        self.assertEqual(job.result['cost_cny'],'0.20')

    def test_legacy_approved_application_joins_or_returns_for_capacity_review(self):
        from importlib import import_module
        with scope(self.teamspace):
            opening=TeamOpening.objects.create(team=self.team,title='旧招聘',description='历史申请迁移')
            accepted=TeamApplication.objects.create(opening=opening,applicant=self.person,state='accepted',reviewed_by=self.owner)
            blocked=TeamApplication.objects.create(opening=opening,applicant=self.stranger,state='accepted',reviewed_by=self.owner)
        apps=MigrationExecutor(connection).loader.project_state([('core','0042_complete_legacy_applications')]).apps
        import_module('core.migrations.0042_complete_legacy_applications').complete(apps,connection.schema_editor())
        accepted.refresh_from_db();blocked.refresh_from_db()
        self.assertEqual(accepted.state,'joined')
        self.assertEqual(blocked.state,'pending')
        self.assertEqual(TeamMembership.objects.get(team=self.team,user=self.person).role,'member')
        self.assertFalse(TeamMembership.objects.filter(team=self.team,user=self.stranger).exists())
        self.assertTrue(AccountNotice.objects.filter(user=self.person,application=accepted).exists())

    def test_group_bulk_members_and_contextual_navigation(self):
        import os
        from pathlib import Path
        from .models import ChatGroup,GroupMember,Friendship
        Friendship.objects.create(first=self.owner,second=self.person)
        group=ChatGroup.objects.create(owner=self.person,name='独立协作群')
        GroupMember.objects.create(group=group,user=self.person,admin=True)
        url=reverse('group_manage',args=[group.pk])
        response=self.client.post(url,{'action':'add_many','users':[self.owner.pk]},HTTP_ACCEPT='application/json')
        self.assertEqual(response.status_code,200)
        self.assertTrue(GroupMember.objects.get(group=group,user=self.owner).active)
        response=self.client.post(url,{'action':'remove_many','users':[self.person.pk]},HTTP_ACCEPT='application/json')
        self.assertEqual(response.status_code,403)
        pages={
            'v4-home.html':reverse('workspace_home'),
            'v4-project.html':reverse('project_detail',args=[self.project.pk]),
            'v4-talents.html':reverse('talent_market'),
            'v4-assistant.html':reverse('ai_assistant'),
            'v4-group.html':reverse('group_chat',args=[group.pk]),
        }
        self.accept(self.offer(project=self.project))
        for name,url in pages.items():
            response=self.client.get(url);self.assertEqual(response.status_code,200,name)
            if os.environ.get('WORKBENCH_CAPTURE_UI'):
                folder=Path(os.environ['WORKBENCH_CAPTURE_UI']);folder.mkdir(parents=True,exist_ok=True);(folder/name).write_bytes(response.content)
        self.client.force_login(self.owner)
        response=self.client.get(reverse('messages_teams')+'?team='+str(self.team.pk))
        self.assertContains(response,'team-context-tabs')
        self.assertNotContains(response,'community-actions')
        if os.environ.get('WORKBENCH_CAPTURE_UI'):(folder/'v4-team.html').write_bytes(response.content)
