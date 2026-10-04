import json
import uuid
from unittest.mock import patch
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from core.tests import WorkbenchTestCase
from .models import Provider,PoolModel,PriceVersion,AssistantJob,AssistantConversation,PoolSettings
from . import quotas

class AssistantRetryTests(WorkbenchTestCase):
    def setUp(self):
        super().setUp();self.client.force_login(self.dev)
        self.provider=Provider.objects.create(name='Test',base_url='https://example.com/v1')
        self.model=PoolModel.objects.create(provider=self.provider,model_id='test')
        PriceVersion.objects.create(model=self.model,effective_from=timezone.now(),input_rate=1,output_rate=1,cached_rate=1,cache_write_rate=1,cny_exchange_rate=1)
        self.conversation=AssistantConversation.objects.create(user=self.dev,title='对话')

    def post(self,**extra):
        data={'model':self.model.pk,'messages':[{'role':'user','content':'客户端文字'}],**extra}
        return self.client.post(reverse('ai_start'),json.dumps(data),content_type='application/json')

    def fake_start(self,user,model,history,context,conversation,job_id=None,retry_of=None):
        return AssistantJob.objects.create(user=user,conversation=conversation,user_text=history[-1]['content'],context=context,retry_of=retry_of,**({'id':job_id} if job_id else {}))

    @patch('aihub.views.provider_key',return_value='fake-key')
    def test_retry_restores_original_message_reference_and_history(self,_key):
        AssistantJob.objects.create(user=self.dev,conversation=self.conversation,user_text='之前的问题',state='done',result={'text':'之前的答案'})
        failed=AssistantJob.objects.create(user=self.dev,conversation=self.conversation,user_text='原问题',context={'kind':'task','id':self.child.pk},state='error',result={'error':'失败'})
        with patch('aihub.agent.start',side_effect=self.fake_start) as start:
            response=self.post(retry_job=str(failed.pk),context={'kind':'task','id':999},conversation=999)
        self.assertEqual(response.status_code,202)
        args=start.call_args.args
        self.assertEqual(args[2],[{'role':'user','content':'之前的问题'},{'role':'assistant','content':'之前的答案'},{'role':'user','content':'原问题'}])
        self.assertEqual(args[3],failed.context);self.assertEqual(args[4],self.conversation)

    @patch('aihub.views.provider_key',return_value='fake-key')
    def test_duplicate_request_returns_same_job_without_second_start(self,_key):
        nonce=str(uuid.uuid4())
        with patch('aihub.agent.start',side_effect=self.fake_start) as start:
            one=self.post(request_id=nonce);two=self.post(request_id=nonce)
        self.assertEqual(one.status_code,202);self.assertEqual(one.json(),two.json());self.assertEqual(start.call_count,1)

    def test_invalid_message_identifier_returns_400(self):
        for nonce in [True,123,{},'invalid']:
            self.assertEqual(self.post(request_id=nonce).status_code,400)

    def test_retry_ownership_and_live_permissions(self):
        job=AssistantJob.objects.create(user=self.owner,state='error',user_text='secret')
        self.assertEqual(self.post(retry_job=str(job.pk)).status_code,404)
        job=AssistantJob.objects.create(user=self.dev,state='error',user_text='original',context={'kind':'task','id':999999})
        self.assertEqual(self.post(retry_job=str(job.pk)).status_code,403)

    def test_failed_history_contains_retry_metadata(self):
        job=AssistantJob.objects.create(user=self.dev,conversation=self.conversation,state='error',user_text='original',context={'kind':'task','id':self.child.pk},result={'error':'failed'})
        data=self.client.get(reverse('ai_conversation',args=[self.conversation.pk])).json()
        self.assertEqual(data['messages'][1]['retry'],{'job':str(job.pk),'text':'original','context':job.context})
        poll=self.client.get(reverse('ai_job',args=[job.pk])).json();self.assertEqual(poll['request']['text'],'original')

    def test_retried_history_shows_one_user_message_and_latest_reply(self):
        original=AssistantJob.objects.create(user=self.dev,conversation=self.conversation,state='error',user_text='original',result={'error':'failed'})
        AssistantJob.objects.create(user=self.dev,conversation=self.conversation,state='done',user_text='original',result={'text':'success'},retry_of=original)
        rows=self.client.get(reverse('ai_conversation',args=[self.conversation.pk])).json()['messages']
        self.assertEqual([(row['role'],row['text']) for row in rows],[('user','original'),('assistant','success')])

class VendorQuotaTests(WorkbenchTestCase):
    def setUp(self):
        super().setUp();cache.clear();self.client.force_login(self.admin)
        PoolSettings.objects.create(pk=1,owner=self.admin)
        self.provider=Provider.objects.create(name='MiniMax',base_url='https://api.minimaxi.com/v1')

    def query(self,kind='auto'):
        return self.client.post(reverse('api_provider_quota',args=[self.provider.pk]),json.dumps({'kind':kind}),content_type='application/json')

    @patch('aihub.quotas.provider_key',return_value='sk-cp-fake')
    @patch('aihub.quotas.json_request')
    def test_minimax_plan_counts_percentages_reset_and_auth(self,network,_key):
        network.return_value={'model_remains':[{'model_name':'general','current_interval_total_count':100,'current_interval_usage_count':30,'current_interval_remaining_percent':70,'end_time':1800000000000,'current_weekly_total_count':1000,'current_weekly_usage_count':600,'current_weekly_remaining_percent':60}]}
        result=self.query().json();self.assertFalse(result['stale']);self.assertEqual(result['value']['windows'][0]['remaining'],70)
        self.assertEqual(result['value']['windows'][1]['remaining'],600);self.assertIn('T',result['value']['windows'][0]['reset_at'])
        self.assertEqual(network.call_args.args[0],'https://api.minimaxi.com/v1/token_plan/remains')
        self.assertEqual(network.call_args.args[1],{'Authorization':'Bearer sk-cp-fake'})
        self.assertNotIn('sk-cp-fake',json.dumps(result))
        self.assertEqual(self.query().json()['error'],'请稍后再刷新。');self.assertEqual(network.call_count,1)

    @patch('aihub.quotas.provider_key',return_value='sk-api-fake')
    @patch('aihub.quotas.json_request',return_value={'available_amount':'12.50','base_resp':{'status_code':0}})
    def test_minimax_account_is_cash_and_preserves_last_result_on_failure(self,network,_key):
        result=self.query().json();self.assertEqual(result['kind'],'account');self.assertEqual(result['value']['balance'],12.5)
        self.provider.refresh_from_db();self.assertEqual(quotas.snapshot(self.provider)['value']['currency'],'CNY')
        cache.clear();network.side_effect=quotas.TransportError('connection_interrupted');failure=self.query().json()
        self.assertTrue(failure['stale']);self.assertEqual(failure['value'],result['value']);self.assertTrue(failure['error'])

    @patch('aihub.quotas.provider_key',return_value='fake-key')
    @patch('aihub.quotas.json_request',return_value={'code':200,'data':{'limits':[{'type':'TOKENS_LIMIT','usage':100,'currentValue':40,'percentage':40,'nextResetTime':1800000000000}]}})
    def test_zhipu_quota_uses_raw_key_and_does_not_claim_cash(self,network,_key):
        self.provider.base_url='https://open.bigmodel.cn/api/coding/paas/v4';self.provider.save()
        result=self.query().json();self.assertEqual(result['kind'],'plan');self.assertEqual(result['value']['windows'][0]['remaining'],60)
        self.assertEqual(network.call_args.args[1],{'Authorization':'fake-key'});self.assertNotIn('balance',result['value'])

    @patch('aihub.quotas.provider_key',return_value='fake-key')
    @patch('aihub.quotas.json_request')
    def test_qwen_and_unrecognized_host_never_receive_keys(self,network,_key):
        for address in ['https://dashscope.aliyuncs.com/compatible-mode/v1','https://api.minimaxi.com.evil.test/v1','https://custom.example/v1']:
            self.provider.base_url=address;self.provider.save();result=self.query().json();self.assertFalse(result['supported']);self.assertIsNone(result['value'])
        network.assert_not_called()

    @patch('aihub.quotas.provider_key',return_value='new-key')
    def test_changed_key_hides_cached_old_account(self,_key):
        self.provider.quota_snapshot={'fingerprint':'old','value':{'balance':999}}
        self.assertIsNone(quotas.snapshot(self.provider)['value'])

    def test_only_pool_owner_can_query_vendor_balances(self):
        self.client.force_login(self.dev);self.assertEqual(self.query().status_code,403)
        self.client.logout();self.assertEqual(self.query().status_code,401)

    @patch('aihub.views.provider_key',return_value='test-key')
    @patch('aihub.quotas.provider_key',return_value='test-key')
    @patch('aihub.quotas.json_request')
    def test_render_never_waits_for_vendor_and_shows_controls(self,network,*_keys):
        response=self.client.get(reverse('api_manage'));self.assertContains(response,'厂商余额 / 套餐额度');self.assertContains(response,'刷新额度');self.assertNotContains(response,'test-key');network.assert_not_called()
        import os
        from pathlib import Path
        target=os.environ.get('WORKBENCH_CAPTURE_UI')
        if target:
            path=Path(target);path.mkdir(parents=True,exist_ok=True)
            (path/'pool-manage.html').write_bytes(response.content)
            (path/'assistant.html').write_bytes(self.client.get(reverse('ai_assistant'),{'kind':'task','id':self.child.pk}).content)
