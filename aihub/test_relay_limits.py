"""Configurable transport bounds; realistic long inputs never silently split."""
import json
import io
from contextlib import ExitStack
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from .models import ApiRateWindow, Call, MemberToken, PoolSettings
from .rate_limits import gate, RateLimited
from .service import create_token
from .test_relay_contract import RelayFixture


class RelayLimitsTests(RelayFixture, TestCase):
    def long_chat(self, text, **extra):
        return {'model':self.alias,'messages':[{'role':'user','content':text}],'max_tokens':64,**extra}

    def test_361_kib_single_message_reaches_supplier_intact(self):
        text='paper '*((361*1024)//6)
        with patch('aihub.service.invoke',return_value=self.result()) as supplier:
            response=self.request_chat(self.long_chat(text))
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(supplier.call_args.args[2][0]['content'],text)
        call=Call.objects.get()
        self.assertEqual(call.status,'success')
        self.assertEqual(call.cost_cny,Decimal('.002'))

    def test_chinese_single_message_above_old_character_limit(self):
        text='论文分析'*26000
        with patch('aihub.service.invoke',return_value=self.result()) as supplier:
            response=self.request_chat(self.long_chat(text))
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(supplier.call_args.args[2][0]['content'],text)

    def test_body_above_old_django_two_mib_limit(self):
        text='a'*(2*1024*1024+100)
        with patch('aihub.service.invoke',return_value=self.result()) as supplier:
            response=self.request_chat(self.long_chat(text))
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(supplier.call_args.args[2][0]['content'],text)

    @override_settings(WORKBENCH_RELAY_MAX_REQUEST_BYTES=300000)
    def test_configured_body_limit_returns_actionable_413_without_charge(self):
        with patch('aihub.service.invoke') as supplier:
            response=self.request_chat(self.long_chat('a'*361000))
        self.assertEqual(response.status_code,413)
        self.assertEqual(response.json()['error']['code'],'request_too_large')
        self.assertEqual(response.json()['error']['limits']['max_bytes'],300000)
        self.assertEqual(response['X-Request-Body-Limit'],'300000')
        self.assertEqual(response['x-should-retry'],'false')
        supplier.assert_not_called()
        self.assertFalse(Call.objects.exists())

    @override_settings(WORKBENCH_RELAY_MAX_CONTEXT_BYTES=300000)
    def test_context_limit_is_consistent_and_rejects_before_supplier(self):
        with patch('aihub.service.invoke') as supplier:
            response=self.request_chat(self.long_chat('a'*361000))
        self.assertEqual(response.status_code,413,response.content)
        self.assertEqual(response.json()['error']['code'],'context_too_large')
        supplier.assert_not_called()
        self.assertFalse(Call.objects.exists())

    def test_invalid_model_in_large_request_still_has_normal_validation_error(self):
        with patch('aihub.service.invoke') as supplier:
            response=self.request_chat(self.long_chat('a'*361000,model='does-not-exist'))
        self.assertEqual(response.status_code,400,response.content)
        self.assertNotEqual(response.json()['error']['code'],'request_too_large')
        supplier.assert_not_called()
        self.assertFalse(Call.objects.exists())

    def test_large_request_still_respects_member_budget(self):
        self.config.default_weekly_limit=Decimal('.01')
        self.config.save(update_fields=['default_weekly_limit'])
        with patch('aihub.service.invoke') as supplier:
            response=self.request_chat(self.long_chat('a'*361000))
        self.assertEqual(response.status_code,429,response.content)
        self.assertEqual(response.json()['error']['code'],'insufficient_quota')
        supplier.assert_not_called()
        self.assertFalse(Call.objects.exists())

    def test_large_streamed_request_reaches_supplier_and_settles_once(self):
        text='a'*361000
        events=[{'choices':[{'index':0,'delta':{'content':'OK'},'finish_reason':None}]},
                {'choices':[{'index':0,'delta':{},'finish_reason':'stop'}]},
                {'choices':[],'usage':{'prompt_tokens':1000,'completion_tokens':500}}]
        def frames(*args,**kwargs):yield from events
        with patch('aihub.gateway.json_events',side_effect=frames) as supplier:
            response=self.request_chat(self.long_chat(text,stream=True,stream_options={'include_usage':True}))
            self.assertEqual(response.status_code,200)
            body=b''.join(response.streaming_content)
        self.assertIn(b'data: [DONE]',body)
        self.assertEqual(supplier.call_args.args[2]['messages'][0]['content'],text)
        call=Call.objects.get()
        self.assertEqual(call.status,'success')
        self.assertEqual(call.cost_cny,Decimal('.002'))
        self.assertFalse(any(row.leases for row in ApiRateWindow.objects.all()))

    def test_more_than_80_messages_and_12_tools_are_accepted(self):
        messages=[{'role':'user','content':'small message'} for _ in range(81)]
        tools=[{'type':'function','function':{'name':'tool_'+str(i),'parameters':{'type':'object'}}} for i in range(13)]
        with patch('aihub.service.invoke',return_value=self.result()) as supplier:
            response=self.request_chat(self.long_chat('unused',messages=messages,tools=tools))
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(len(supplier.call_args.args[2]),81)
        self.assertEqual(len(supplier.call_args.args[3]),13)

    def test_team_can_raise_concurrency_without_bypassing_account_cap(self):
        self.config.key_concurrent=4
        self.config.account_concurrent=3
        self.config.save(update_fields=['key_concurrent','account_concurrent'])
        with ExitStack() as stack:
            for _ in range(3):stack.enter_context(gate(self.member,self.token))
            with self.assertRaises(RateLimited):
                with gate(self.member,self.token):pass
        self.assertFalse(any(row.leases for row in ApiRateWindow.objects.all()))

    def test_zero_disables_optional_gate_limits(self):
        self.config.account_rpm=self.config.key_rpm=1
        self.config.account_concurrent=self.config.key_concurrent=0
        self.config.save()
        with gate(self.member,self.token):pass
        with self.assertRaises(RateLimited):
            with gate(self.member,self.token):pass
        self.config.account_rpm=self.config.key_rpm=0
        self.config.save()
        with ExitStack() as stack:
            for _ in range(5):stack.enter_context(gate(self.member,self.token))

    def test_active_key_cap_is_configurable(self):
        self.config.max_active_keys=1
        self.config.save(update_fields=['max_active_keys'])
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):create_token(self.member,'second')
        self.config.max_active_keys=0
        self.config.save(update_fields=['max_active_keys'])
        create_token(self.member,'second')
        self.assertEqual(MemberToken.objects.filter(user=self.member).count(),2)

    def test_limits_are_visible_to_own_key(self):
        value=self.get_api('/v1/key').json()['limits']
        self.assertEqual(value['request_body_bytes'],16*1024*1024)
        self.assertEqual(value['account_concurrent'],3)
        self.assertEqual(value['key_concurrent'],2)

    def test_only_manager_can_edit_limits_and_edits_preserve_budget(self):
        data={'action':'call_limits','account_rpm':120,'account_concurrent':8,'key_rpm':100,
              'key_concurrent':6,'max_active_keys':0}
        path=f'/api-pool/?ownership={self.space.pk}&scope=team'
        self.assertEqual(self.client.post(path,data).status_code,403)
        self.client.force_login(self.owner)
        response=self.client.post(path,data)
        self.assertEqual(response.status_code,302)
        self.assertIn('ownership='+str(self.space.pk),response['Location'])
        self.config.refresh_from_db()
        self.assertEqual(self.config.key_concurrent,6)
        self.assertEqual(self.config.weekly_limit,100)
        self.assertEqual(self.config.default_weekly_limit,10)

    def test_model_configuration_accepts_larger_supported_output(self):
        self.model.max_output_tokens=65536
        self.model.full_clean()
        self.model.save(update_fields=['max_output_tokens'])
        with patch('aihub.service.invoke',return_value=self.result()) as supplier:
            response=self.request_chat(self.long_chat('hello',max_tokens=65536))
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(supplier.call_args.args[4],65536)

    def test_long_reasoning_is_not_silently_truncated(self):
        from .providers import normalize
        reasoning='r'*170000
        result=normalize(self.model,{'choices':[{'message':{'content':'answer','reasoning_content':reasoning}}]})
        self.assertEqual(result['reasoning'],reasoning)


@override_settings(DEBUG=True)
class RelayResponseLimitsTests(TestCase):
    def response(self, data, content_type='application/json'):
        stream=io.BytesIO(data)
        stream.headers={'Content-Type':content_type}
        return stream

    def test_inference_response_above_old_eight_mib_limit(self):
        from .network import raw_request
        data=b'a'*(8*1024*1024+1)
        with patch('aihub.network._open',return_value=self.response(data)):
            self.assertEqual(raw_request('http://localhost/v1',body={}),data)

    @override_settings(WORKBENCH_INFERENCE_MAX_RESPONSE_BYTES=65536)
    def test_oversized_response_retains_uncertain_billing_status(self):
        from .network import raw_request, TransportError
        with patch('aihub.network._open',return_value=self.response(b'a'*65537)):
            with self.assertRaises(TransportError) as failure:raw_request('http://localhost/v1',body={})
        self.assertEqual(failure.exception.code,'response_too_large')
        self.assertTrue(failure.exception.uncertain)

    def test_sse_line_above_old_one_mib_limit_is_supported(self):
        from .network import json_events
        chunk={'choices':[{'delta':{'content':'a'*(1024*1024+1)}}]}
        data=('data: '+json.dumps(chunk)+'\n\ndata: [DONE]\n\n').encode()
        with patch('aihub.network._open',return_value=self.response(data,'text/event-stream')):
            self.assertEqual(list(json_events('http://localhost/v1',{},{})),[chunk])

    @override_settings(WORKBENCH_INFERENCE_MAX_EVENT_BYTES=65536)
    def test_sse_line_limit_remains_bounded_and_uncertain(self):
        from .network import json_events, TransportError
        with patch('aihub.network._open',return_value=self.response(b'data: '+b'a'*65537,'text/event-stream')):
            with self.assertRaises(TransportError) as failure:list(json_events('http://localhost/v1',{},{}))
        self.assertTrue(failure.exception.uncertain)
