import hashlib
import json
import os
from pathlib import Path
from unittest.mock import patch
from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from core.models import Experiment, Project
from .models import MemberToken, PoolModel, PoolSettings, PriceVersion, Provider
from .service import create_token


class PersonalApiTests(TestCase):
    from core.testing_ownership import TeamFixtureClient
    client_class = TeamFixtureClient
    def setUp(self):
        self.owner=User.objects.create_user('api-owner',is_staff=True)
        self.member=User.objects.create_user('api-member')
        self.other=User.objects.create_user('api-other')
        PoolSettings.objects.create(pk=1,owner=self.owner)
        self.provider=Provider.objects.create(name='Test',base_url='https://example.com/v1')
        self.model=PoolModel.objects.create(provider=self.provider,model_id='test-model',supports_tools=False)
        self.experiment=Experiment.objects.create(number='EXP-MY',title='我的实验',created_by=self.member)
        PriceVersion.objects.create(model=self.model,effective_from=timezone.now(),input_rate=1,output_rate=2,cached_rate=1,cache_write_rate=1)
        self.client.force_login(self.member)

    def capture(self,name,response):
        if os.environ.get('WORKBENCH_CAPTURE_UI'):
            folder=Path(os.environ['WORKBENCH_CAPTURE_UI']);folder.mkdir(parents=True,exist_ok=True)
            (folder/name).write_bytes(response.content)

    @patch('aihub.views.provider_key',return_value='supplier-secret-must-stay-hidden')
    def test_member_entry_and_only_callable_models(self,_key):
        PoolModel.objects.create(provider=self.provider,model_id='unpriced')
        PoolModel.objects.create(provider=self.provider,model_id='disabled',enabled=False)
        paused=Provider.objects.create(name='Paused',base_url='https://paused.example.com/v1',enabled=False)
        PoolModel.objects.create(provider=paused,model_id='paused-model')
        response=self.client.get(reverse('api_pool'),secure=True)
        self.assertContains(response,'我的 API Key')
        self.assertContains(response,'data-open-api-key')
        self.assertContains(response,'https://testserver/api/pool/v1')
        self.assertContains(response,f'<option value="{self.provider.pk}/test-model">')
        self.assertNotContains(response,'供脚本和其他软件调用')
        self.assertNotContains(response,'supplier-secret-must-stay-hidden')
        self.assertNotContains(response,'/unpriced</option>')
        self.assertNotContains(response,'/disabled</option>')
        self.assertContains(response,'personal-api.js')
        self.assertContains(response,'EXP-MY');self.assertContains(response,'关联实验（必选）')
        self.assertIn('no-store',response['Cache-Control'])
        self.capture('personal-api.html',response)

    @patch('aihub.views.provider_key',return_value='supplier-secret-must-stay-hidden')
    def test_new_key_shown_once_digest_only_and_member_isolation(self,_key):
        foreign=create_token(self.other,'Other key')
        response=self.client.post(reverse('api_pool'),{'action':'new_token','label':'实验脚本','experiment_id':self.experiment.pk})
        key=response.context['fresh_token'];token=MemberToken.objects.get(user=self.member)
        self.assertTrue(key.startswith('fy_'));self.assertEqual(token.digest,hashlib.sha256(key.encode()).hexdigest())
        self.assertEqual(token.label,'实验脚本');self.assertNotEqual(token.digest,key)
        self.assertEqual(token.experiment,self.experiment);self.assertTrue(token.experiment_bound)
        self.assertContains(response,'id="personal-api-secret"')
        self.assertContains(response,'复制 Key');self.assertContains(response,key,count=1)
        self.assertContains(response,'完整 Key 只在本次生成后显示')
        self.assertNotContains(response,foreign);self.assertNotContains(response,'Other key')
        self.assertIn('no-store',response['Cache-Control'])
        self.capture('personal-api-fresh.html',response)
        again=self.client.get(reverse('api_pool'))
        self.assertNotContains(again,key);self.assertNotContains(again,'id="personal-api-secret"')
        self.assertNotContains(again,'复制 Key')

    @patch('aihub.views.provider_key',return_value='fake')
    def test_personal_key_works_for_models_then_revocation_is_immediate(self,_key):
        key=create_token(self.member,'')
        token=MemberToken.objects.get(user=self.member)
        self.assertEqual(token.label,'我的 API Key')
        response=self.client.get(reverse('pool_models'),HTTP_AUTHORIZATION='Bearer '+key)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['data'][0]['id'],f'{self.provider.pk}/test-model')
        self.client.post(reverse('api_pool'),{'action':'revoke_token','id':token.pk})
        response=self.client.get(reverse('pool_models'),HTTP_AUTHORIZATION='Bearer '+key)
        self.assertEqual(response.status_code,401);self.assertIn('已撤销',response.json()['error']['message'])

    def test_cannot_revoke_another_members_key(self):
        create_token(self.other,'Other key');token=MemberToken.objects.get(user=self.other)
        self.client.post(reverse('api_pool'),{'action':'revoke_token','id':token.pk})
        token.refresh_from_db();self.assertIsNone(token.revoked_at)

    def test_ten_key_limit_and_anonymous_access(self):
        for _ in range(10):create_token(self.member,'实验脚本')
        response=self.client.post(reverse('api_pool'),{'action':'new_token','experiment_id':self.experiment.pk})
        self.assertContains(response,'最多保留 10 个 API Key')
        self.assertEqual(MemberToken.objects.filter(user=self.member).count(),10)
        self.client.logout()
        self.assertEqual(self.client.get(reverse('api_pool')).status_code,302)
        self.assertEqual(self.client.get(reverse('pool_models')).status_code,401)

    @override_settings(WORKBENCH_DESKTOP=True)
    @patch('aihub.views.provider_key',return_value='fake')
    def test_desktop_entry_and_team_screen_separation(self,_key):
        response=self.client.get(reverse('api_pool'));self.assertContains(response,'我的 API Key')
        self.capture('personal-api-desktop.html',response)
        self.client.force_login(self.owner)
        response=self.client.get(reverse('api_pool'),{'scope':'team'})
        self.assertNotContains(response,'id="my-api-key"')
        self.assertNotContains(response,'生成 API Key')

    @patch('aihub.views.provider_key',return_value='')
    def test_empty_model_list_keeps_key_generation(self,_key):
        response=self.client.get(reverse('api_pool'))
        self.assertContains(response,'生成 API Key')
        self.assertNotContains(response,f'<option value="{self.provider.pk}/test-model">')
        self.capture('personal-api-empty.html',response)

    @patch('aihub.views.provider_key',return_value='fake')
    def test_model_id_escaped_and_assistant_label_plain(self,_key):
        self.model.model_id="quote'\"<script>alert(1)</script>";self.model.save()
        response=self.client.get(reverse('api_pool'))
        self.assertNotContains(response,'<script>alert(1)</script>')
        self.assertContains(response,'&lt;script&gt;')
        self.capture('personal-api-escaped.html',response)
        source=(Path(settings.BASE_DIR)/'static/aihub/assistant.js').read_text(encoding='utf-8')
        self.assertNotIn('资料摘要模式',source)

    def chat(self,body,key=None):
        key=key or create_token(self.member,'Test')
        return self.client.post(reverse('pool_chat'),json.dumps(body),content_type='application/json',HTTP_AUTHORIZATION='Bearer '+key)

    def payload(self):
        return {'model':f'{self.provider.pk}/test-model','messages':[{'role':'user','content':'实验输出'}],
                'experiment_id':self.experiment.pk,'stream':False}

    @patch('aihub.views.execute')
    def test_independent_calls_require_positive_integer_experiment_before_inference(self,execute):
        key=create_token(self.member,'Test')
        for value in (None,0,-1,True,'1',1.5,[],{},10**30):
            with self.subTest(value=value):
                body=self.payload();body['experiment_id']=value
                response=self.chat(body,key)
                self.assertEqual(response.status_code,400);self.assertIn('experiment_id',response.json()['error'])
        body=self.payload();body.pop('experiment_id');body['project_id']=1
        self.assertEqual(self.chat(body,key).status_code,400);execute.assert_not_called()

    @patch('aihub.views.execute')
    def test_experiment_listing_and_calls_share_permissions_and_archive_rules(self,execute):
        own_project=Project.objects.create(name='参与项目',owner=self.other,created_by=self.owner)
        own_project.members.add(self.member)
        shared=Experiment.objects.create(number='EXP-SHARED',title='协作实验',created_by=self.other,project=own_project)
        foreign=Experiment.objects.create(number='EXP-FOREIGN',title='他人独立实验',created_by=self.other)
        unrelated=Project.objects.create(name='他人项目',owner=self.other,created_by=self.owner)
        excluded=Experiment.objects.create(number='EXP-OTHER',title='他人项目实验',created_by=self.other,project=unrelated)
        archived=Project.objects.create(name='归档项目',owner=self.member,created_by=self.owner,archived_at=timezone.now())
        old=Experiment.objects.create(number='EXP-OLD',title='归档实验',created_by=self.member,project=archived)
        key=create_token(self.member,'Test');self.client.logout()
        response=self.client.get(reverse('pool_experiments'),HTTP_AUTHORIZATION='Bearer '+key)
        self.assertEqual(response.status_code,200)
        self.assertEqual({row['id'] for row in response.json()['data']},{self.experiment.pk,shared.pk})
        response=self.client.get(reverse('pool_experiments'),{'q':'协作'},HTTP_AUTHORIZATION='Bearer '+key)
        self.assertEqual([row['id'] for row in response.json()['data']],[shared.pk])
        for identifier in (foreign.pk,excluded.pk,old.pk,99999):
            body=self.payload();body['experiment_id']=identifier
            self.assertEqual(self.chat(body,key).status_code,400)
        own_project.members.remove(self.member)
        body=self.payload();body['experiment_id']=shared.pk
        self.assertEqual(self.chat(body,key).status_code,400)
        execute.assert_not_called()
        admin_key=create_token(self.owner,'Admin')
        response=self.client.get(reverse('pool_experiments'),HTTP_AUTHORIZATION='Bearer '+admin_key)
        self.assertIn(foreign.pk,{row['id'] for row in response.json()['data']})
        self.assertNotIn(old.pk,{row['id'] for row in response.json()['data']})

    @patch('aihub.views.provider_key',return_value='fake')
    @patch('aihub.views.execute')
    def test_valid_call_attributes_experiment_to_key_owner_not_browser_user(self,execute,_key):
        execute.return_value={'counts':{'input_tokens':10,'output_tokens':5,'cached_tokens':0,'cache_write_tokens':0,'reasoning_tokens':0},
            'text':'实验结果','tool_calls':[],'call_id':'test-call','cost':'0.00002','currency':'CNY',
            'cost_cny':'0.00002','price_version':1,'status':'done'}
        key=create_token(self.member,'Test');self.client.force_login(self.other)
        response=self.chat(self.payload(),key);self.assertEqual(response.status_code,200)
        self.assertEqual(execute.call_args.args[0].pk,self.member.pk)
        self.assertEqual(execute.call_args.kwargs['experiment'],self.experiment)
        self.assertIsNone(execute.call_args.kwargs['project'])
        self.assertEqual(response.json()['workbench']['experiment_id'],self.experiment.pk)
        self.assertEqual(response.json()['workbench']['experiment_number'],'EXP-MY')

    @patch('aihub.views.execute')
    def test_mismatched_or_invalid_project_cannot_replace_experiment(self,execute):
        project=Project.objects.create(name='My project',owner=self.member,created_by=self.owner)
        self.experiment.project=project;self.experiment.save()
        key=create_token(self.member,'Test')
        for identifier in (True,0,'1',[],{},project.pk+1):
            body=self.payload();body['project_id']=identifier
            self.assertEqual(self.chat(body,key).status_code,400)
        execute.assert_not_called()

    @patch('aihub.views.execute')
    def test_generation_requires_permitted_experiment(self,execute):
        foreign=Experiment.objects.create(number='FOREIGN',title='Other',created_by=self.other)
        for value in ('',0,True,'bad',foreign.pk,'9'*30):
            response=self.client.post(reverse('api_pool'),{'action':'new_token','experiment_id':value})
            self.assertEqual(response.status_code,200);self.assertFalse(response.context['fresh_token'])
        self.assertFalse(MemberToken.objects.filter(user=self.member).exists());execute.assert_not_called()

    @patch('aihub.views.provider_key',return_value='fake')
    @patch('aihub.views.execute')
    def test_bound_key_accepts_standard_request_and_refuses_reassignment(self,execute,_key):
        execute.return_value={'counts':None,'text':'Output','tool_calls':[],'call_id':'call',
            'cost':None,'currency':'CNY','cost_cny':None,'price_version':1,'status':'unknown'}
        key=create_token(self.member,'Bound',self.experiment)
        body=self.payload();body.pop('experiment_id')
        response=self.chat(body,key);self.assertEqual(response.status_code,200)
        self.assertEqual(execute.call_args.kwargs['experiment'],self.experiment)
        execute.reset_mock()
        another=Experiment.objects.create(number='ANOTHER',title='Another',created_by=self.member)
        for value in (another.pk,None,str(self.experiment.pk),True):
            body['experiment_id']=value
            self.assertEqual(self.chat(body,key).status_code,400)
        execute.assert_not_called()
        body.pop('experiment_id');self.experiment.delete()
        self.assertEqual(self.chat(body,key).status_code,400);execute.assert_not_called()

    @patch('aihub.service.provider_key',return_value='fake')
    @patch('aihub.views.provider_key',return_value='fake')
    @patch('aihub.service.invoke')
    def test_bound_experiment_call_settles_member_points_and_persists_attribution(self,invoke,_view_key,_service_key):
        from .models import Call, BudgetWeek
        project=Project.objects.create(name='实验项目',owner=self.member,created_by=self.owner)
        self.experiment.project=project;self.experiment.save()
        invoke.return_value={'id':'mock-call','text':'实验输出','tool_calls':[],'counts':{'input_tokens':100,'output_tokens':50,'cached_tokens':0,'cache_write_tokens':0,'reasoning_tokens':0}}
        key=create_token(self.member,'实验调用',self.experiment)
        body=self.payload();body.pop('experiment_id')
        response=self.chat(body,key)
        self.assertEqual(response.status_code,200)
        call=Call.objects.get(user=self.member)
        self.assertEqual(call.experiment_id,self.experiment.pk)
        self.assertEqual(call.project_id,project.pk)
        self.assertEqual(call.status,'success');self.assertGreater(call.cost_cny,0)
        self.assertEqual(BudgetWeek.objects.get(scope='user:'+str(self.member.pk)).spent,call.cost_cny)
        page=self.client.get(reverse('api_pool'))
        self.assertContains(page,reverse('experiment_detail',args=[self.experiment.pk]))

    def test_api_run_can_start_before_results_then_update(self):
        import json
        from core.models import ExperimentRun
        key=create_token(self.member,'run',self.experiment)
        url=reverse('pool_experiment_run',args=[self.experiment.pk])
        response=self.client.post(url,json.dumps({'title':'First run','status':'running'}),content_type='application/json',HTTP_AUTHORIZATION='Bearer '+key)
        self.assertEqual(response.status_code,201);run_id=response.json()['id']
        response=self.client.post(url,json.dumps({'run_id':run_id,'title':'First run','result':'Output','status':'completed'}),content_type='application/json',HTTP_AUTHORIZATION='Bearer '+key)
        self.assertEqual(response.status_code,200);self.assertEqual(ExperimentRun.objects.count(),1)
        self.assertEqual(ExperimentRun.objects.get().result,'Output')
        self.assertEqual(self.client.get(reverse('pool_experiments'),HTTP_AUTHORIZATION='Bearer '+key).json()['data'][0]['status'],'design')

    def test_api_run_respects_bound_key_and_cannot_edit_other_members_run(self):
        import json
        from core.models import ExperimentRun
        key=create_token(self.member,'run',self.experiment)
        foreign=Experiment.objects.create(number='EXP-FOREIGN',title='Other',created_by=self.other)
        url=reverse('pool_experiment_run',args=[foreign.pk])
        self.assertEqual(self.client.post(url,'{}',content_type='application/json',HTTP_AUTHORIZATION='Bearer '+key).status_code,400)
        run=ExperimentRun.objects.create(experiment=self.experiment,created_by=self.other,title='Other')
        response=self.client.post(reverse('pool_experiment_run',args=[self.experiment.pk]),json.dumps({'run_id':run.pk}),content_type='application/json',HTTP_AUTHORIZATION='Bearer '+key)
        self.assertEqual(response.status_code,404)

    def test_api_run_rejects_archived_experiment_bad_input_and_anonymous_calls(self):
        key=create_token(self.member,'run',self.experiment)
        url=reverse('pool_experiment_run',args=[self.experiment.pk])
        self.assertEqual(self.client.post(url,'{}',content_type='application/json').status_code,401)
        self.assertEqual(self.client.post(url,'{"status":"wrong"}',content_type='application/json',HTTP_AUTHORIZATION='Bearer '+key).status_code,400)
        self.experiment.status='archived';self.experiment.save()
        self.assertEqual(self.client.post(url,'{}',content_type='application/json',HTTP_AUTHORIZATION='Bearer '+key).status_code,400)
