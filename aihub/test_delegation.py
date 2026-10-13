import json
from unittest.mock import patch
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, SimpleTestCase
from django.urls import reverse
from django.utils import timezone
from core.models import Team, TeamMembership, Workspace, Project, Task, SharedDocument, DocumentVersion, DocumentDraft
from core.tenancy import scope
from .models import AgentGrant, AgentOperation, AgentPluginSetting, AssistantJob
from .delegation import issue, definitions, execute_operation
from .tool_registry import Registry, Plugin, Tool, validate


class ToolRegistryTests(SimpleTestCase):
    def test_duplicate_registration_is_atomic(self):
        registry=Registry();tool=Tool('read','读取','读取',{},())
        registry.register(Plugin('first','一',(tool,)))
        with self.assertRaises(ValueError):registry.register(Plugin('second','二',(tool,)))
        self.assertNotIn('second',registry.plugins)

    def test_schema_rejects_boolean_integer_and_unknown_arguments(self):
        schema={'type':'object','properties':{'id':{'type':'integer','minimum':1}},'required':['id']}
        for value in ({'id':True},{'id':0},{'id':1,'handler':'os.system'},{}):
            with self.subTest(value=value),self.assertRaises(ValidationError):validate(schema,value)


class DelegationTests(TestCase):
    def setUp(self):
        self.user=User.objects.create_user('agent-owner')
        self.member=User.objects.create_user('agent-member')
        self.team=Team.objects.create(name='Agent team',owner=self.user)
        self.membership=TeamMembership.objects.create(team=self.team,user=self.user,role='owner')
        TeamMembership.objects.create(team=self.team,user=self.member,role='member')
        self.space=Workspace.objects.create(kind='team',team=self.team)
        self.personal=Workspace.objects.get_or_create(owner=self.user,defaults={'kind':'personal'})[0]
        self.current=scope(self.personal);self.current.__enter__();self.addCleanup(self.current.__exit__,None,None,None)
        with scope(self.space):
            self.project=Project.objects.create(name='Agent project',owner=self.user,created_by=self.user)
            self.project.members.add(self.member)
            self.other=Project.objects.create(name='Other project',owner=self.user,created_by=self.user)
            self.task=Task.objects.create(project=self.project,title='Existing task',assignee=self.member,created_by=self.user)
        self.document=SharedDocument.objects.create(workspace=self.space,project=self.project,title='Plan',kind='online',created_by=self.user)
        self.version=DocumentVersion.objects.create(document=self.document,number=1,content={'type':'doc','content':[{'type':'paragraph','content':[{'type':'text','text':'original'}]}]},created_by=self.user,approved_by=self.user)
        self.document.current=self.version;self.document.save(update_fields=['current'])
        self.grant=issue(self.user,self.project.pk,['create_task','update_task_progress','save_document_draft'])
        self.job=AssistantJob.objects.create(user=self.user,authorization=self.grant)

    def execute(self,name='create_task',args=None,job=None):
        return execute_operation(self.user,job or self.job,name,args or {'project_id':self.project.pk,'title':'New task'})

    def test_readonly_catalog_has_no_write_tools(self):
        names={tool['function']['name'] for tool in definitions(self.user)}
        self.assertIn('read_record',names);self.assertNotIn('create_task',names)

    def test_delegated_catalog_only_exposes_granted_tools(self):
        self.grant.actions=['create_task'];self.grant.save()
        names={tool['function']['name'] for tool in definitions(self.user,self.grant,web=False)}
        self.assertIn('create_task',names);self.assertNotIn('save_document_draft',names);self.assertNotIn('search_web',names)

    def test_direct_write_call_has_no_authority(self):
        from .agent import run_tool
        with self.assertRaises(PermissionDenied):run_tool(self.user,'create_task',{'project_id':self.project.pk,'title':'No'})

    def test_create_assigns_real_task_and_returns_link(self):
        result=self.execute(args={'project_id':self.project.pk,'title':'Assigned','assignee_id':self.member.pk})
        task=Task.all_objects.get(pk=result['source']['id'])
        self.assertEqual(task.workspace_id,self.space.pk);self.assertEqual(task.created_by,self.user);self.assertEqual(task.assignee,self.member)
        self.assertEqual(result['source']['url'],reverse('task_detail',args=[task.pk]));self.assertTrue(result['receipt'])

    def test_replay_does_not_consume_budget_or_create_again(self):
        self.grant.max_operations=1;self.grant.save()
        first=self.execute();again=self.execute()
        self.assertEqual(first['receipt'],again['receipt']);self.assertTrue(again['replayed'])
        self.assertEqual(Task.all_objects.filter(title='New task').count(),1)
        self.grant.refresh_from_db();self.assertEqual(self.grant.used_operations,1)
        with self.assertRaises(PermissionDenied):self.execute(args={'project_id':self.project.pk,'title':'Second'})

    def test_retry_group_reuses_committed_receipt(self):
        first=self.execute()
        retry=AssistantJob.objects.create(user=self.user,authorization=self.grant,retry_of=self.job,operation_group=self.job.operation_group)
        again=self.execute(job=retry);self.assertEqual(first['receipt'],again['receipt'])

    def test_independent_jobs_can_create_identical_tasks(self):
        self.execute();other=AssistantJob.objects.create(user=self.user,authorization=self.grant)
        self.execute(job=other);self.assertEqual(Task.all_objects.filter(title='New task').count(),2)

    def test_ungranted_job_cannot_write(self):
        self.job.authorization=None;self.job.save(update_fields=['authorization'])
        with self.assertRaises(PermissionDenied):self.execute()

    def test_other_project_is_denied(self):
        with self.assertRaises(PermissionDenied):self.execute(args={'project_id':self.other.pk,'title':'No'})

    def test_expired_grant_is_denied(self):
        self.grant.expires_at=timezone.now()-timezone.timedelta(seconds=1);self.grant.save()
        with self.assertRaises(PermissionDenied):self.execute()

    def test_revoked_grant_is_denied_including_replay(self):
        self.execute();self.grant.revoked_at=timezone.now();self.grant.save()
        with self.assertRaises(PermissionDenied):self.execute()

    def test_disabled_plugin_denies_existing_grant(self):
        AgentPluginSetting.objects.create(user=self.user,plugin='tasks',enabled=False)
        with self.assertRaises(PermissionDenied):self.execute()

    def test_cancelled_job_has_no_more_side_effects(self):
        self.job.cancel_requested=True;self.job.save(update_fields=['cancel_requested'])
        with self.assertRaises(ValidationError):self.execute()

    def test_removed_member_loses_write_and_replay_permissions(self):
        self.execute();self.membership.active=False;self.membership.save()
        with self.assertRaises(PermissionDenied):self.execute()

    def test_deactivated_account_is_denied(self):
        self.user.is_active=False;self.user.save()
        with self.assertRaises(PermissionDenied):self.execute()

    def test_foreign_user_grant_is_denied(self):
        self.grant.user=self.member;self.grant.save()
        with self.assertRaises(PermissionDenied):self.execute()

    def test_missing_business_right_cannot_be_delegated(self):
        with self.assertRaises(PermissionDenied):issue(self.member,self.project.pk,['create_task'])

    def test_unknown_action_cannot_be_delegated(self):
        with self.assertRaises(PermissionDenied):issue(self.user,self.project.pk,['delete_team'])

    def test_partial_write_and_receipt_roll_back_together(self):
        from .workspace_tools import write_tool
        def broken(user,name,args):
            write_tool(user,name,args);raise ValidationError('failure after save')
        with patch('aihub.workspace_tools.write_tool',side_effect=broken),self.assertRaises(ValidationError):self.execute()
        self.assertEqual(AgentOperation.objects.count(),0);self.assertFalse(Task.all_objects.filter(title='New task').exists())
        self.grant.refresh_from_db();self.assertEqual(self.grant.used_operations,0)

    def test_progress_is_written_and_version_conflict_prevents_overwrite(self):
        args={'task_id':self.task.pk,'progress':50,'expected_progress':0}
        self.execute('update_task_progress',args)
        self.task.refresh_from_db();self.assertEqual(self.task.progress,50)
        with self.assertRaises(ValidationError):self.execute('update_task_progress',{**args,'progress':60})
        self.task.refresh_from_db();self.assertEqual(self.task.progress,50)

    def test_submitted_task_cannot_change_progress(self):
        with scope(self.space):self.task.status='submitted';self.task.save(update_fields=['status'])
        with self.assertRaises(ValidationError):self.execute('update_task_progress',{'task_id':self.task.pk,'progress':50,'expected_progress':0})

    def test_draft_save_preserves_approved_version(self):
        result=self.execute('save_document_draft',{'document_id':self.document.pk,'draft_id':0,'generation':0,'text':'Plan\nNext step'})
        draft=DocumentDraft.objects.get(pk=result['draft_id']);self.assertEqual(draft.author,self.user);self.assertEqual(draft.generation,1)
        self.version.refresh_from_db();self.assertEqual(self.version.content['content'][0]['content'][0]['text'],'original')
        self.assertIn('?draft=',result['source']['url'])

    def test_draft_conflict_preserves_user_edits(self):
        draft=DocumentDraft.objects.create(document=self.document,author=self.user,base=self.version,content=self.version.content,generation=3)
        with self.assertRaises(ValidationError):self.execute('save_document_draft',{'document_id':self.document.pk,'draft_id':draft.pk,'generation':2,'text':'Overwrite'})
        draft.refresh_from_db();self.assertEqual(draft.content,self.version.content);self.assertEqual(draft.generation,3)

    def test_existing_draft_cannot_be_replaced_as_new(self):
        DocumentDraft.objects.create(document=self.document,author=self.user,base=self.version,content=self.version.content)
        with self.assertRaises(ValidationError):self.execute('save_document_draft',{'document_id':self.document.pk,'draft_id':0,'generation':0,'text':'Overwrite'})

    def test_schema_validation_prevents_bool_progress(self):
        with self.assertRaises(ValidationError):self.execute('update_task_progress',{'task_id':self.task.pk,'progress':True,'expected_progress':0})

    def test_plugin_and_authorization_api_use_personal_scope(self):
        self.client.force_login(self.user)
        response=self.client.get(reverse('ai_capabilities'))
        self.assertEqual(response.status_code,200);self.assertEqual(len(response.json()['plugins']),len(__import__('aihub.tool_registry',fromlist=['registry']).registry.plugins))
        response=self.client.post(reverse('ai_capabilities'),json.dumps({'action':'grant','project':self.project.pk,'actions':['create_task']}),content_type='application/json')
        self.assertEqual(response.status_code,201)

    def test_http_revoke_stops_running_granted_jobs(self):
        self.client.force_login(self.user)
        response=self.client.post(reverse('ai_capabilities'),json.dumps({'action':'revoke','id':str(self.grant.pk)}),content_type='application/json')
        self.assertEqual(response.status_code,200);self.job.refresh_from_db();self.assertTrue(self.job.cancel_requested)

    def test_http_cannot_revoke_another_user_grant(self):
        self.client.force_login(self.member)
        response=self.client.post(reverse('ai_capabilities'),json.dumps({'action':'revoke','id':str(self.grant.pk)}),content_type='application/json')
        self.assertEqual(response.status_code,400);self.grant.refresh_from_db();self.assertIsNone(self.grant.revoked_at)

    def test_native_model_calls_execute_real_commands_and_publish_receipts(self):
        from .agent import worker
        from .testing_private_history import funded_model
        model=funded_model(self.user,model_id='agent-test')
        self.job.billing_workspace=model.workspace;self.job.save(update_fields=['billing_workspace'])
        calls=[{'id':'create','type':'function','function':{'name':'create_task','arguments':json.dumps({'project_id':self.project.pk,'title':'Native task'})}},
            {'id':'draft','type':'function','function':{'name':'save_document_draft','arguments':json.dumps({'document_id':self.document.pk,'draft_id':0,'generation':0,'text':'Native plan'})}}]
        replies=[{'text':'','tool_calls':calls,'status':'success','cost_cny':'0','counts':None},
            {'text':'任务和修改稿已保存。','tool_calls':[],'status':'success','cost_cny':'0','counts':None}]
        with patch('aihub.agent.CAPACITY'),patch('aihub.agent.connections.close_all'),patch('aihub.agent.close_old_connections'),patch('aihub.agent.execute',side_effect=replies) as execute:
            worker(self.job.pk,self.user.pk,model.pk,[{'role':'user','content':'创建任务并保存规划'}],None)
        self.job.refresh_from_db();self.assertEqual(self.job.state,'done');self.assertEqual(execute.call_count,2)
        self.assertEqual(Task.all_objects.filter(title='Native task').count(),1);self.assertEqual(AgentOperation.objects.count(),2)
        writes=[step for step in self.job.result['activity'] if step.get('effect')=='write']
        self.assertTrue(all(step['status']=='success' and step['receipt'] for step in writes))
        self.assertEqual(len(self.job.result['sources']),2)

    def test_retry_start_preserves_operation_group_and_checks_grant(self):
        from .agent import start
        from .testing_private_history import funded_model
        model=funded_model(self.user,model_id='retry-test')
        self.job.state='error';self.job.save(update_fields=['state'])
        with patch('aihub.agent.CAPACITY'),patch('aihub.agent.threading.Thread'):
            retry=start(self.user,model,[{'role':'user','content':'retry'}],None,retry_of=self.job,authorization=self.grant)
        self.assertEqual(retry.operation_group,self.job.operation_group);self.assertEqual(retry.authorization,self.grant)

    def test_expired_grant_stops_before_paid_model_call(self):
        from .agent import worker
        from .testing_private_history import funded_model
        model=funded_model(self.user,model_id='expired-test')
        self.job.billing_workspace=model.workspace;self.job.save(update_fields=['billing_workspace'])
        self.grant.expires_at=timezone.now()-timezone.timedelta(seconds=1);self.grant.save()
        with patch('aihub.agent.CAPACITY'),patch('aihub.agent.connections.close_all'),patch('aihub.agent.close_old_connections'),patch('aihub.agent.execute') as execute:
            worker(self.job.pk,self.user.pk,model.pk,[{'role':'user','content':'create'}],None)
        self.job.refresh_from_db();self.assertEqual(self.job.state,'error');self.assertEqual(execute.call_count,0)
