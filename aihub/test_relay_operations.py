"""Native wire contracts, token admission, routing and quota isolation."""
import json
from decimal import Decimal
from unittest.mock import patch
from django.test import TestCase
from django.utils import timezone
from .models import Call,MemberToken,PoolModel,Provider,PriceVersion
from .service import create_token
from .test_relay_contract import RelayFixture
from .token_estimates import input_estimate
from .network import TransportError

class RelayOperationsTests(RelayFixture,TestCase):
    def setUp(self):
        super().setUp()
        for name in ('aihub.native_relay.provider_key','aihub.native_views.provider_key'):
            mocked=patch(name,return_value='synthetic-upstream-key');mocked.start();self.addCleanup(mocked.stop)

    def native(self,path,body,**headers):
        return self.client.post(path,json.dumps(body),content_type='application/json',
            **(headers or {'HTTP_AUTHORIZATION':'Bearer '+self.secret}))

    def response_value(self):
        return {'id':'resp_test','object':'response','status':'completed','output':[],
                'usage':{'input_tokens':1000,'output_tokens':500,'input_tokens_details':{'cached_tokens':0}}}

    def protocol(self,name):
        self.provider.protocol=name;self.provider.save(update_fields=['protocol'])

    def test_default_output_does_not_reserve_entire_model_window(self):
        from .relay import chat_payload
        payload=chat_payload({'messages':[{'role':'user','content':'hi'}]},self.model)
        self.assertEqual(payload['limit'],4096)
        self.model.max_output_tokens=512
        self.assertEqual(chat_payload({'messages':[{'role':'user','content':'hi'}]},self.model)['limit'],512)

    def test_chat_json_preserves_reasoning_signature_details(self):
        details=[{'type':'reasoning.encrypted','data':'synthetic-signature'}]
        result={**self.result(),'assistant_message':{'role':'assistant','reasoning_details':details}}
        with patch('aihub.service.invoke',return_value=result):response=self.request_chat()
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['choices'][0]['message']['reasoning_details'],details)

    def test_known_tokenizer_is_offline_and_does_not_count_bytes_as_tokens(self):
        self.model.model_id='gpt-4o'
        with patch('urllib.request.urlopen',side_effect=AssertionError('No network at admission')):
            estimate=input_estimate(self.model,[{'role':'user','content':'paper analysis '*3000}],[])
        self.assertEqual(estimate['method'],'o200k_base')
        self.assertLess(estimate['tokens'],estimate['bytes']//2)

    def test_chinese_estimate_and_explicit_conservative_mode(self):
        body=[{'role':'user','content':'研究结果分析'*10000}]
        automatic=input_estimate(self.model,body,[])
        self.model.tokenizer='bytes';conservative=input_estimate(self.model,body,[])
        self.assertLess(automatic['tokens'],conservative['tokens'])
        self.assertEqual(conservative['method'],'bytes')

    def test_responses_preserves_native_parameters_and_settles_supplier_usage(self):
        self.client.logout()
        body={'model':self.alias,'input':'hello','max_output_tokens':64,'store':False,
              'reasoning':{'effort':'high'},'include':['reasoning.encrypted_content'],'metadata':{'test':'yes'}}
        with patch('aihub.native_relay.json_request',return_value=self.response_value()) as supplier:
            response=self.native('/v1/responses',body)
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(supplier.call_args.args[2]['include'],body['include'])
        self.assertEqual(supplier.call_args.args[2]['model'],'test-model')
        call=Call.objects.get();self.assertEqual(call.api_kind,'responses')
        self.assertEqual(call.cost_cny,Decimal('.002'));self.assertEqual(call.provider_request_id,'resp_test')

    def test_responses_stream_preserves_event_types_and_usage(self):
        rows=[{'type':'response.created','response':{'id':'resp_live'}},
              {'type':'response.output_text.delta','delta':'first'},
              {'type':'response.completed','response':{**self.response_value(),'id':'resp_live'}}]
        def frames(*args,**kwargs):yield from rows
        with patch('aihub.native_relay.json_events',side_effect=frames):
            response=self.native('/v1/responses',{'model':self.alias,'input':'hi','max_output_tokens':64,'stream':True})
            self.assertEqual(response.status_code,200)
            source=iter(response.streaming_content)
            self.assertIn(b'event: response.created',next(source))
            self.assertEqual(Call.objects.get().status,'running')
            self.assertIn(b'first',next(source));remaining=b''.join(source)
        self.assertIn(b'response.completed',remaining)
        call=Call.objects.get();self.assertEqual(call.status,'success');self.assertIsNotNone(call.first_token_ms)
        self.assertEqual(call.cost_cny,Decimal('.002'))

    def test_native_stream_quota_rejection_is_an_http_error_before_stream_starts(self):
        self.config.default_weekly_limit=0;self.config.save()
        with patch('aihub.native_relay.json_events') as supplier:
            response=self.native('/v1/responses',{'model':self.alias,'input':'hi','stream':True})
        self.assertEqual(response.status_code,429,response.content);supplier.assert_not_called()
        self.assertFalse(Call.objects.exists())

    def test_native_failure_does_not_retry_an_uncertain_billable_request(self):
        with patch('aihub.native_relay.json_request',side_effect=TransportError('connection_interrupted',True)) as supplier:
            response=self.native('/v1/responses',{'model':self.alias,'input':'hi','max_output_tokens':64})
        self.assertEqual(response.status_code,502);self.assertEqual(supplier.call_count,1)
        self.assertEqual(Call.objects.get().status,'unknown')

    def test_native_stream_disconnect_preserves_unknown_reservation(self):
        def frames(*args,**kwargs):
            yield {'type':'response.output_text.delta','delta':'partial'}
            raise AssertionError('The client closed before the next event')
        with patch('aihub.native_relay.json_events',side_effect=frames):
            response=self.native('/v1/responses',{'model':self.alias,'input':'hi','stream':True})
            source=iter(response.streaming_content);next(source);response.close()
        self.assertEqual(Call.objects.get().status,'unknown')

    def test_anthropic_header_and_body_are_forwarded_without_rewriting(self):
        self.protocol('anthropic')
        raw={'id':'msg_test','content':[{'type':'text','text':'hello'}],
             'usage':{'input_tokens':100,'output_tokens':20,'cache_read_input_tokens':5},'stop_reason':'end_turn'}
        body={'model':self.alias,'max_tokens':64,'messages':[{'role':'user','content':'hi'}],
              'thinking':{'type':'enabled','budget_tokens':32}}
        with patch('aihub.native_relay.json_request',return_value=raw) as supplier:
            response=self.native('/v1/messages',body,HTTP_X_API_KEY=self.secret,HTTP_ANTHROPIC_BETA='test-2026-01-01')
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(supplier.call_args.args[1]['x-api-key'],'synthetic-upstream-key')
        self.assertEqual(supplier.call_args.args[2]['thinking'],body['thinking'])
        call=Call.objects.get();self.assertEqual(call.input_tokens,105);self.assertEqual(call.cached_tokens,5)

    def test_gemini_native_model_path_and_key_header(self):
        self.protocol('gemini')
        raw={'responseId':'gem_test','candidates':[{'content':{'parts':[{'text':'hello'}]},'finishReason':'STOP'}],
             'usageMetadata':{'promptTokenCount':100,'totalTokenCount':120}}
        with patch('aihub.native_relay.json_request',return_value=raw) as supplier:
            response=self.native('/v1beta/models/'+self.alias+':generateContent',
                                 {'contents':[{'parts':[{'text':'hi'}]}]},HTTP_X_GOOG_API_KEY=self.secret)
        self.assertEqual(response.status_code,200,response.content)
        self.assertTrue(supplier.call_args.args[0].endswith('/models/test-model:generateContent'))
        self.assertEqual(Call.objects.get().output_tokens,20)

    def test_embeddings_settle_only_input_tokens(self):
        raw={'object':'list','data':[{'embedding':[0.1,0.2],'index':0}], 'usage':{'prompt_tokens':100,'total_tokens':100}}
        with patch('aihub.native_relay.json_request',return_value=raw):
            response=self.native('/v1/embeddings',{'model':self.alias,'input':['one','two'],'encoding_format':'float'})
        self.assertEqual(response.status_code,200,response.content)
        call=Call.objects.get();self.assertEqual(call.output_tokens,0);self.assertEqual(call.cost_cny,Decimal('.0001'))

    def test_conflicting_credentials_and_cookie_only_are_not_authenticated(self):
        body={'model':self.alias,'input':'hi'}
        self.assertEqual(self.native('/v1/responses',body,HTTP_X_API_KEY='wrong',HTTP_AUTHORIZATION='Bearer '+self.secret).status_code,401)
        self.assertEqual(self.client.post('/v1/responses',json.dumps(body),content_type='application/json').status_code,401)

    def test_unknown_shared_supplier_objects_are_rejected_without_charge(self):
        with patch('aihub.native_relay.json_request') as supplier:
            response=self.native('/v1/responses',{'model':self.alias,'input':[{'type':'input_file','file_id':'file_someone_else'}]})
        self.assertEqual(response.status_code,400);supplier.assert_not_called();self.assertFalse(Call.objects.exists())

    def test_only_the_originating_key_can_read_a_stored_response(self):
        with patch('aihub.native_relay.json_request',return_value=self.response_value()):
            self.native('/v1/responses',{'model':self.alias,'input':'hi'})
        other=create_token(self.member,'another')
        with patch('aihub.native_views.json_request') as supplier:
            response=self.client.get('/v1/responses/resp_test',HTTP_AUTHORIZATION='Bearer '+other)
        self.assertEqual(response.status_code,404);supplier.assert_not_called()

    def test_response_polling_can_settle_known_usage_once(self):
        with patch('aihub.native_relay.json_request',return_value={'id':'resp_test','status':'in_progress','output':[]}):
            self.native('/v1/responses',{'model':self.alias,'input':'hi','background':True})
        self.assertEqual(Call.objects.get().status,'unknown')
        with patch('aihub.native_views.json_request',return_value=self.response_value()):
            self.assertEqual(self.get_api('/v1/responses/resp_test').status_code,200)
            self.assertEqual(self.get_api('/v1/responses/resp_test').status_code,200)
        self.assertEqual(Call.objects.get().cost_cny,Decimal('.002'))

    def test_token_counter_endpoint_creates_no_inference_charge(self):
        self.client.logout()
        with patch('aihub.native_views.json_request',return_value={'input_tokens':25}):
            response=self.native('/v1/responses/input_tokens',{'model':self.alias,'input':'hi'})
        self.assertEqual(response.status_code,200);self.assertFalse(Call.objects.exists())

    def test_background_cancel_is_owned_idempotent_and_accounts_known_usage(self):
        self.client.logout()
        with patch('aihub.native_relay.json_request',return_value={'id':'resp_test','status':'in_progress','output':[]}):
            self.native('/v1/responses',{'model':self.alias,'input':'hi','background':True})
        cancelled={**self.response_value(),'status':'cancelled'}
        with patch('aihub.native_views.json_request',return_value=cancelled) as supplier:
            for _ in range(2):
                response=self.native('/v1/responses/resp_test/cancel',{})
                self.assertEqual(response.status_code,200,response.content)
            self.assertEqual(supplier.call_args.kwargs['method'],'POST')
            self.assertTrue(supplier.call_args.args[0].endswith('/responses/resp_test/cancel'))
        call=Call.objects.get();self.assertEqual(call.cost_cny,Decimal('.002'))
        self.assertEqual(call.error_code,'upstream_response_cancelled')
        from .models import BudgetWeek
        self.assertFalse(BudgetWeek.objects.exclude(reserved=0).exists())

    def test_cancel_wrong_key_and_unconfirmed_result_preserve_ledger(self):
        with patch('aihub.native_relay.json_request',return_value={'id':'resp_test','status':'in_progress','output':[]}):
            self.native('/v1/responses',{'model':self.alias,'input':'hi','background':True})
        other=create_token(self.member,'cancel-other')
        with patch('aihub.native_views.json_request') as supplier:
            response=self.native('/v1/responses/resp_test/cancel',{},HTTP_AUTHORIZATION='Bearer '+other)
        self.assertEqual(response.status_code,404);supplier.assert_not_called()
        with patch('aihub.native_views.json_request',side_effect=TransportError('connection_interrupted',True)):
            response=self.native('/v1/responses/resp_test/cancel',{})
        self.assertEqual(response.status_code,502)
        self.assertEqual(Call.objects.get().status,'unknown')

    def test_mismatched_response_id_never_settles(self):
        with patch('aihub.native_relay.json_request',return_value={'id':'resp_test','status':'in_progress','output':[]}):
            self.native('/v1/responses',{'model':self.alias,'input':'hi','background':True})
        wrong={**self.response_value(),'id':'resp_other'}
        with patch('aihub.native_views.json_request',return_value=wrong):
            self.assertEqual(self.get_api('/v1/responses/resp_test').status_code,502)
            self.assertEqual(self.native('/v1/responses/resp_test/cancel',{}).status_code,502)
        self.assertEqual(Call.objects.get().status,'unknown')

    def test_public_alias_uses_priority_and_preserves_legacy_model_id(self):
        self.model.public_alias='team-chat';self.model.route_priority=10;self.model.save()
        provider=Provider.objects.create(name='Second',base_url='https://other.example/v1')
        second=PoolModel.objects.create(provider=provider,model_id='upstream-name',public_alias='team-chat',route_priority=0)
        PriceVersion.objects.create(model=second,effective_from=timezone.now(),input_rate=1,output_rate=2,cached_rate=0,cache_write_rate=0)
        with patch('aihub.service.invoke',return_value=self.result()) as supplier:
            response=self.request_chat({'model':'team-chat','messages':[{'role':'user','content':'hi'}],'max_tokens':64})
        self.assertEqual(response.status_code,200,response.content);self.assertEqual(supplier.call_args.args[0].pk,second.pk)
        with patch('aihub.service.invoke',return_value=self.result()) as supplier:
            response=self.request_chat()
        self.assertEqual(supplier.call_args.args[0].pk,self.model.pk)

    def test_alias_pool_cannot_bypass_allowed_model_scope(self):
        self.model.public_alias='team-chat';self.model.save()
        self.token.allowed_models=[self.model.pk];self.token.save()
        from .channels import resolve_model
        self.assertEqual(resolve_model(self.member,'team-chat',self.token).pk,self.model.pk)

    def test_alias_catalog_deduplicates_and_has_native_list_metadata(self):
        self.model.public_alias='team-chat';self.model.save()
        response=self.get_api('/v1/models')
        self.assertEqual(response.json()['data'][0]['id'],'team-chat')
        self.assertFalse(response.json()['has_more'])

    def test_extra_chat_parameters_and_image_parts_reach_the_supplier(self):
        self.model.supports_images=True;self.model.save()
        body={'model':self.alias,'max_tokens':64,'messages':[{'role':'user','content':[
            {'type':'text','text':'describe'}, {'type':'image_url','image_url':{'url':'https://image.example/test.png','detail':'low'}}]}],
            'metadata':{'session':'one'},'store':False,'service_tier':'default','logprobs':False}
        with patch('aihub.service.invoke',return_value=self.result()) as supplier:
            response=self.request_chat(body)
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(supplier.call_args.args[2][0]['_parts'],body['messages'][0]['content'])
        self.assertEqual(supplier.call_args.args[5]['metadata'],{'session':'one'})

    def test_tiered_price_settles_actual_input_band_and_old_price_is_unchanged(self):
        self.price.tiers=[{'above_tokens':1000,'input_rate':'3','output_rate':'4','cached_rate':'1','cache_write_rate':'2'}]
        self.price.save(update_fields=['tiers'])
        call=self.admit()
        from .service import settle
        settle(call,{'input_tokens':2000,'output_tokens':10,'cached_tokens':0,'cache_write_tokens':0,'reasoning_tokens':0})
        call.refresh_from_db();self.assertEqual(call.cost_cny,Decimal('.00604'))
        self.price.refresh_from_db();self.assertEqual(self.price.input_rate,Decimal('1'))

    def test_automatic_reconciliation_requires_matching_supplier_record(self):
        call=self.admit();call.status='unknown';call.api_kind='responses';call.provider_request_id='resp_own';call.save()
        from .operations import reconcile
        with patch('aihub.operations.provider_key',return_value='synthetic-key'),patch('aihub.operations.json_request',return_value=self.response_value()):
            self.assertEqual(reconcile()['settled'],0)
        call.refresh_from_db();self.assertEqual(call.status,'unknown')

    def test_tools_and_metadata_named_conversation_are_not_mistaken_for_shared_state(self):
        body={'model':self.alias,'input':'hello','metadata':{'conversation':'label'},
              'tools':[{'type':'function','name':'read','parameters':{'type':'object','properties':{'conversation':{'type':'string'}}}}]}
        with patch('aihub.native_relay.json_request',return_value=self.response_value()):response=self.native('/v1/responses',body)
        self.assertEqual(response.status_code,200,response.content)

    def test_three_background_responses_do_not_open_the_provider_circuit(self):
        from .models import ProviderHealth
        with patch('aihub.native_relay.json_request',return_value={'id':'resp_queued','status':'queued','output':[]}):
            for _ in range(3):self.assertEqual(self.native('/v1/responses',{'model':self.alias,'input':'hi'}).status_code,200)
        self.assertEqual(ProviderHealth.objects.get(provider=self.provider).failures,0)

    def test_stream_quota_rejection_releases_a_recovery_probe(self):
        from .models import ProviderHealth
        ProviderHealth.objects.create(provider=self.provider,cooldown_until=timezone.now()-timezone.timedelta(seconds=1))
        self.config.default_weekly_limit=0;self.config.save()
        response=self.native('/v1/responses',{'model':self.alias,'input':'hi','stream':True})
        self.assertEqual(response.status_code,429)
        self.assertIsNone(ProviderHealth.objects.get(provider=self.provider).probe_token)

    def test_native_stream_safe_rejection_switches_before_first_frame(self):
        provider=Provider.objects.create(name='Backup native',base_url='https://backup.example/v1')
        second=PoolModel.objects.create(provider=provider,model_id=self.model.model_id)
        PriceVersion.objects.create(model=second,effective_from=timezone.now(),input_rate=1,output_rate=2,cached_rate=0,cache_write_rate=0)
        self.model.fallback_model=second;self.model.save()
        def frames(url,*args,**kwargs):
            if url.startswith(self.provider.base_url):raise TransportError('http_429',False)
            yield {'type':'response.output_text.delta','delta':'OK'}
            yield {'type':'response.completed','response':self.response_value()}
        with patch('aihub.native_relay.json_events',side_effect=frames) as supplier:
            response=self.native('/v1/responses',{'model':self.alias,'input':'hi','stream':True})
            data=b''.join(response.streaming_content)
        self.assertIn(b'OK',data);self.assertEqual(supplier.call_count,2)
        self.assertEqual(Call.objects.filter(status='success').count(),1)
        self.assertEqual(Call.objects.filter(status='failed',cost_cny=0).count(),1)

    def test_failed_native_response_with_usage_is_accounted_without_unknown_hold(self):
        raw={**self.response_value(),'status':'failed','error':{'code':'server_error','message':'failed after work'}}
        with patch('aihub.native_relay.json_request',return_value=raw):response=self.native('/v1/responses',{'model':self.alias,'input':'hi'})
        self.assertEqual(response.status_code,200)
        call=Call.objects.get();self.assertEqual(call.cost_cny,Decimal('.002'));self.assertEqual(call.status,'success')
        self.assertEqual(call.error_code,'upstream_response_failed')

    def test_connection_changes_do_not_rewrite_new_call_history(self):
        with patch('aihub.native_relay.json_request',return_value=self.response_value()):self.native('/v1/responses',{'model':self.alias,'input':'hi'})
        self.model.model_id='changed';self.model.save()
        self.provider.base_url='https://changed.example/v1';self.provider.save()
        call=Call.objects.get();self.assertEqual(call.upstream_model,'test-model');self.assertEqual(call.provider_endpoint,'https://example.com/v1')
        with patch('aihub.native_views.json_request') as supplier:response=self.get_api('/v1/responses/resp_test')
        self.assertEqual(response.status_code,409);supplier.assert_not_called()


from types import SimpleNamespace
from django.test import SimpleTestCase
from .native_streams import stream as native_stream

class NativeStreamTests(SimpleTestCase):
    def model(self,protocol):
        return SimpleNamespace(provider=SimpleNamespace(protocol=protocol,base_url='https://supplier.example/v1'),
                               model_id='test',output_parameter='max_tokens')

    def anthropic(self):
        return [
            {'type':'message_start','message':{'id':'msg_live','usage':{'input_tokens':10,'output_tokens':1,'cache_read_input_tokens':5}}},
            {'type':'content_block_start','index':0,'content_block':{'type':'thinking','thinking':''}},
            {'type':'content_block_delta','index':0,'delta':{'type':'thinking_delta','thinking':'think'}},
            {'type':'content_block_delta','index':0,'delta':{'type':'signature_delta','signature':'signed'}},
            {'type':'content_block_start','index':1,'content_block':{'type':'text','text':''}},
            {'type':'content_block_delta','index':1,'delta':{'type':'text_delta','text':'first'}},
            {'type':'content_block_delta','index':1,'delta':{'type':'text_delta','text':' second'}},
            {'type':'message_delta','delta':{'stop_reason':'end_turn'},'usage':{'output_tokens':20}},
            {'type':'message_stop'}]

    def test_anthropic_is_incremental_and_preserves_signatures_and_cumulative_usage(self):
        with patch('aihub.native_streams.json_events',return_value=iter(self.anthropic())):
            iterator=native_stream(self.model('anthropic'),'fake',[{'role':'user','content':'hi'}],[],64)
            self.assertEqual(next(iterator)['delta']['reasoning_content'],'think')
            self.assertEqual(next(iterator)['delta']['content'],'first')
            rows=list(iterator)
        result=rows[-1]['result']
        self.assertEqual(result['text'],'first second');self.assertEqual(result['counts']['output_tokens'],20)
        self.assertEqual(result['counts']['input_tokens'],15);self.assertEqual(result['native'][0]['signature'],'signed')

    def test_anthropic_tool_arguments_are_forwarded_in_parts(self):
        rows=self.anthropic()[:1]+[
            {'type':'content_block_start','index':0,'content_block':{'type':'tool_use','id':'tool1','name':'read','input':{}}},
            {'type':'content_block_delta','index':0,'delta':{'type':'input_json_delta','partial_json':'{"id":'}},
            {'type':'content_block_delta','index':0,'delta':{'type':'input_json_delta','partial_json':'1}'}},
            {'type':'message_delta','delta':{'stop_reason':'tool_use'},'usage':{'output_tokens':20}}, {'type':'message_stop'}]
        with patch('aihub.native_streams.json_events',return_value=iter(rows)):
            output=list(native_stream(self.model('anthropic'),'fake',[{'role':'user','content':'hi'}],[],64))
        self.assertEqual(output[1]['delta']['tool_calls'][0]['function']['arguments'],'{"id":')
        self.assertEqual(json.loads(output[-1]['result']['tool_calls'][0]['function']['arguments']),{'id':1})

    def test_gemini_is_incremental_and_keeps_thought_signatures(self):
        rows=[{'candidates':[{'content':{'parts':[{'text':'first','thought':True,'thoughtSignature':'signed'}]}}]},
              {'candidates':[{'content':{'parts':[{'text':'answer'}]},'finishReason':'STOP'}],
               'usageMetadata':{'promptTokenCount':10,'totalTokenCount':35,'thoughtsTokenCount':5}}]
        with patch('aihub.native_streams.json_events',return_value=iter(rows)) as source:
            output=list(native_stream(self.model('gemini'),'fake',[{'role':'user','content':'hi'}],[],64))
        self.assertEqual(output[0]['delta']['reasoning_content'],'first');self.assertEqual(output[1]['delta']['content'],'answer')
        self.assertEqual(output[-1]['result']['native'][0]['thoughtSignature'],'signed')
        self.assertEqual(output[-1]['result']['counts']['output_tokens'],25)
        self.assertIn(':streamGenerateContent?alt=sse',source.call_args.args[0])

    def test_incomplete_native_stream_is_uncertain(self):
        with patch('aihub.native_streams.json_events',return_value=iter(self.anthropic()[:-1])):
            with self.assertRaises(TransportError) as raised:list(native_stream(self.model('anthropic'),'fake',[],[],64))
        self.assertTrue(raised.exception.uncertain)

    def test_price_feed_uses_only_exact_vendor_matches_and_keeps_tiers(self):
        from .public_prices import reference_price
        provider=SimpleNamespace(base_url='https://api.openai.com/v1')
        row={'litellm_provider':'openai','mode':'chat','input_cost_per_token':.000001,'output_cost_per_token':.000002,
             'input_cost_per_token_above_128k_tokens':.000003,'output_cost_per_token_above_128k_tokens':.000004}
        with patch('aihub.public_prices.cached_fetch',return_value={'test':row}),patch('aihub.public_prices.exchange_rate',return_value={'rate':'7'}):
            result=reference_price(provider,'test')
            self.assertEqual(result['tiers'][0]['above_tokens'],128000)
            self.assertEqual(result['tiers'][0]['input_rate'],'3.000000')
            self.assertIsNone(reference_price(provider,'unknown'))
        row['litellm_provider']='anthropic'
        with patch('aihub.public_prices.cached_fetch',return_value={'test':row}):self.assertIsNone(reference_price(provider,'test'))
