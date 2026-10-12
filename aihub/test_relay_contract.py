"""Relay and reset regressions using synthetic keys and a mocked supplier."""
import hashlib
import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.db import connections
from django.test import TestCase, TransactionTestCase, tag, override_settings
from django.utils import timezone

from core.models import Team, TeamMembership, Workspace, MemberProfile
from core.tenancy import scope
from .models import Allowance, BudgetMonth, BudgetWeek, Call, MemberToken, PoolModel, PriceVersion, PoolSettings, Provider
from .permissions import visible_budget
from .quota_cards import issue, redeem
from .relay import RelayError, chat_payload
from .service import allowance, create_token, reserve, reset_budget, settle, week_now, month_now


COUNTS = {'input_tokens':1000, 'output_tokens':500, 'cached_tokens':0,
          'cache_write_tokens':0, 'reasoning_tokens':0}


class RelayFixture:
    def setUp(self):
        self.owner=User.objects.create_user('relay-owner')
        self.member=User.objects.create_user('relay-member')
        self.admin=User.objects.create_user('relay-other')
        for user in (self.owner,self.member,self.admin):MemberProfile.objects.get_or_create(user=user)
        self.team=Team.objects.create(name='Isolated relay team',owner=self.owner)
        for user,role in ((self.owner,'owner'),(self.member,'member'),(self.admin,'admin')):
            TeamMembership.objects.get_or_create(team=self.team,user=user,defaults={'role':role})
        self.space=Workspace.objects.get_or_create(team=self.team,defaults={'kind':'team'})[0]
        current=scope(self.space);current.__enter__();self.addCleanup(current.__exit__,None,None,None)
        self.config=PoolSettings.objects.create(owner=self.owner,weekly_limit=100,default_weekly_limit=10)
        self.provider=Provider.objects.create(name='Test provider',base_url='https://example.com/v1')
        self.model=PoolModel.objects.create(provider=self.provider,model_id='test-model')
        self.price=PriceVersion.objects.create(model=self.model,effective_from=timezone.now(),input_rate=1,
            output_rate=2,cached_rate=Decimal('.1'),cache_write_rate=Decimal('.5'))
        self.client.force_login(self.member)
        for name in ('aihub.service.provider_key','aihub.views.provider_key','aihub.gateway.provider_key'):
            mocked=patch(name,return_value='synthetic-supplier-key')
            mocked.start();self.addCleanup(mocked.stop)
        self.config.default_weekly_limit=10
        self.config.save(update_fields=['default_weekly_limit'])
        self.secret=create_token(self.member,'test-client')
        self.token=MemberToken.objects.get(digest=hashlib.sha256(self.secret.encode()).hexdigest())
        self.alias=str(self.provider.pk)+'/'+self.model.model_id

    def admit(self, *, token=True):
        return reserve(self.member,self.model,[{'role':'user','content':'hello'}],[],64,'api',None,None,None,
                       api_token=self.token if token else None)

    def request_chat(self, data=None, path='/v1/chat/completions'):
        return self.client.post(path,json.dumps(data or {'model':self.alias,'messages':[{'role':'user','content':'hello'}],'max_tokens':64}),
                                content_type='application/json',HTTP_AUTHORIZATION='Bearer '+self.secret)

    def get_api(self, path):
        return self.client.get(path,HTTP_AUTHORIZATION='Bearer '+self.secret)

    def result(self):
        return {'text':'hello back','tool_calls':[],'reasoning':'short thought','id':'mock-provider-id',
                'counts':dict(COUNTS),'finish_reason':'stop'}


class ResetGenerationTests(RelayFixture, TestCase):
    def test_reset_restores_1000_points_despite_pending_call(self):
        completed=self.admit();settle(completed,None,'success',cost_override=Decimal('3'))
        pending=self.admit();settle(pending,None,'unknown','timeout')
        # Reproduce a large reservation using a synthetic price, not ledger edits.
        self.price.input_rate=1700;self.price.output_rate=1000;self.price.save()
        large=self.admit();settle(large,None,'unknown','timeout')
        self.assertLess(Decimal(visible_budget(self.member)['member_week']['remaining_points']),700)
        reset_budget('user:'+str(self.member.pk),'week',actor=self.owner)
        value=visible_budget(self.member)['member_week']
        self.assertEqual(Decimal(value['remaining_points']),1000)
        self.assertEqual(Decimal(value['reserved_points']),0)
        self.assertEqual(Call.objects.filter(status='unknown').count(),2)
        self.assertEqual(Call.objects.get(pk=completed.pk).cost_cny,3)
        self.assertGreater(BudgetWeek.objects.get(scope='team',week=week_now()).reserved,0)

    def test_late_settlement_preserves_new_calls_reservation(self):
        old=self.admit();settle(old,None,'unknown')
        reset_budget('user:'+str(self.member.pk),'week')
        current=self.admit()
        settle(old,COUNTS);settle(old,COUNTS)
        bucket=BudgetWeek.objects.get(scope='user:'+str(self.member.pk),week=week_now())
        self.assertEqual(bucket.reserved,current.reserved_cny)
        self.assertEqual(bucket.spent-bucket.reset_credit,0)
        settle(current,COUNTS)
        bucket.refresh_from_db()
        self.assertEqual(bucket.reserved,0)
        self.assertEqual(bucket.spent-bucket.reset_credit,Decimal('.002'))
        self.assertEqual(bucket.spent,min(old.reserved_cny,Decimal('.002'))+Decimal('.002'))
        old.refresh_from_db();self.assertEqual(old.cost_cny,Decimal('.002'))

    def test_multiple_resets_and_failed_old_calls_never_make_pending_negative(self):
        oldest=self.admit();reset_budget('user:'+str(self.member.pk),'both')
        middle=self.admit();reset_budget('user:'+str(self.member.pk),'both')
        settle(oldest,COUNTS);settle(middle,None,'failed','connection_failed')
        settle(middle,None,'failed','connection_failed')
        for model,period in ((BudgetWeek,{'week':week_now()}),(BudgetMonth,{'month':month_now()})):
            bucket=model.objects.get(scope='user:'+str(self.member.pk),**period)
            self.assertEqual(bucket.generation,2);self.assertEqual(bucket.reserved,0)
            self.assertEqual(bucket.spent-bucket.reset_credit,0)

    def test_reset_retains_supplemental_balance_and_old_supplemental_reservation(self):
        self.config.default_weekly_limit=0;self.config.save(update_fields=['default_weekly_limit'])
        member=allowance(self.member);member.extra_balance=5;member.save()
        old=self.admit();self.assertEqual(old.extra_reserved_cny,old.reserved_cny)
        self.config.default_weekly_limit=10;self.config.save(update_fields=['default_weekly_limit'])
        reset_budget('user:'+str(self.member.pk),'week')
        member.refresh_from_db();self.assertEqual(member.extra_reserved,old.reserved_cny)
        self.assertEqual(member.extra_balance,5)
        settle(old,COUNTS)
        member.refresh_from_db();self.assertEqual(member.extra_reserved,0)
        self.assertEqual(member.extra_balance,Decimal('4.998'))
        self.assertEqual(Decimal(visible_budget(self.member)['member_week']['remaining_points']),1000)

    def test_pre_upgrade_calls_without_generation_metadata_can_settle_after_reset(self):
        old=self.admit();Call.objects.filter(pk=old.pk).update(quota_generations={});old.refresh_from_db()
        reset_budget('user:'+str(self.member.pk),'week');settle(old,COUNTS)
        self.assertEqual(Decimal(visible_budget(self.member)['member_week']['remaining_points']),1000)
        self.assertEqual(Call.objects.get(pk=old.pk).cost_cny,Decimal('.002'))

    def test_card_can_restore_a_period_occupied_only_by_pending_calls(self):
        from .models import ResetCard
        old=self.admit()
        issue(self.owner,str(self.member.pk),'week',1,7,uuid.uuid4())
        card=ResetCard.objects.get(user=self.member)
        self.assertTrue(redeem(self.member,card.pk));self.assertFalse(redeem(self.member,card.pk))
        settle(old,COUNTS)
        self.assertEqual(Decimal(visible_budget(self.member)['member_week']['remaining_points']),1000)

    def test_member_reset_does_not_reset_monthly_or_team_caps(self):
        old=self.admit()
        reset_budget('user:'+str(self.member.pk),'week')
        self.assertEqual(BudgetMonth.objects.get(scope='user:'+str(self.member.pk),month=month_now()).reserved,old.reserved_cny)
        self.assertEqual(BudgetWeek.objects.get(scope='team',week=week_now()).reserved,old.reserved_cny)


class RelayContractTests(RelayFixture, TestCase):
    def test_standard_and_legacy_model_routes_work_without_browser_session(self):
        self.client.logout()
        for path in ('/v1/models','/api/pool/v1/models'):
            response=self.get_api(path)
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json()['data'][0]['id'],self.alias)
            self.assertNotIn('synthetic-supplier-key',response.content.decode())

    def test_missing_revoked_and_expired_keys_return_json_401(self):
        self.assertEqual(self.client.get('/v1/models').status_code,401)
        MemberToken.objects.filter(pk=self.token.pk).update(expires_at=timezone.now()-timezone.timedelta(seconds=1))
        response=self.get_api('/v1/models')
        self.assertEqual(response.status_code,401);self.assertEqual(response.json()['error']['code'],'invalid_api_key')
        MemberToken.objects.filter(pk=self.token.pk).update(expires_at=None,revoked_at=timezone.now())
        self.assertEqual(self.get_api('/v1/models').status_code,401)

    def test_cookie_cannot_override_key_principal_or_team(self):
        self.client.force_login(self.admin)
        self.admin.member_profile.must_change_password=True;self.admin.member_profile.save()
        response=self.get_api('/v1/key')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['prefix'],self.token.prefix)

    def test_key_owner_must_change_password_is_still_rejected(self):
        self.member.member_profile.must_change_password=True;self.member.member_profile.save()
        self.assertEqual(self.get_api('/v1/models').status_code,403)

    def test_inactive_membership_and_disbanded_team_reject_existing_keys(self):
        TeamMembership.objects.filter(team_id=self.token.team_id,user=self.member).update(active=False)
        self.assertEqual(self.get_api('/v1/key').status_code,403)
        TeamMembership.objects.filter(team_id=self.token.team_id,user=self.member).update(active=True)
        Team.objects.filter(pk=self.token.team_id).update(active=False)
        self.assertEqual(self.get_api('/v1/key').status_code,403)

    def test_model_restriction_applies_to_catalog_and_chat(self):
        other=PoolModel.objects.create(provider=self.provider,model_id='other-model')
        PriceVersion.objects.create(model=other,effective_from=timezone.now(),input_rate=1,output_rate=2,cached_rate=0,cache_write_rate=0)
        MemberToken.objects.filter(pk=self.token.pk).update(allowed_models=[other.pk])
        self.assertEqual(self.get_api('/v1/models').json()['data'][0]['id'],str(self.provider.pk)+'/other-model')
        self.assertEqual(self.request_chat().status_code,403)
        self.assertFalse(Call.objects.exists())

    def test_sdk_shaped_nonstream_response_and_accounting(self):
        self.client.logout()
        with patch('aihub.service.invoke',return_value=self.result()) as supplier:
            response=self.request_chat({'model':self.alias,'messages':[{'role':'developer','content':'be brief'},
                {'role':'user','content':[{'type':'text','text':'hello'}]}],'max_completion_tokens':64,
                'response_format':{'type':'json_object'},'temperature':0,'seed':42})
        self.assertEqual(response.status_code,200,response.content)
        data=response.json();self.assertEqual(data['object'],'chat.completion')
        self.assertEqual(data['choices'][0]['message']['content'],'hello back')
        self.assertEqual(data['choices'][0]['message']['reasoning_content'],'short thought')
        self.assertEqual(data['usage']['total_tokens'],1500)
        self.assertEqual(data['workbench']['cost_cny'],'0.00200000')
        self.assertEqual(response['X-Request-ID'],data['id'])
        self.assertEqual(supplier.call_args.args[2][0]['role'],'developer')
        call=Call.objects.get();self.assertEqual(call.api_token_id,self.token.pk)
        self.assertEqual(self.get_api('/v1/usage?call_id='+data['id']).json()['data'][0]['status'],'success')

    def test_legacy_chat_alias_retains_compatibility(self):
        with patch('aihub.service.invoke',return_value=self.result()):
            response=self.request_chat(path='/api/pool/v1/chat/completions')
        self.assertEqual(response.status_code,200,response.content)

    def test_pending_reservation_counts_against_key_cap_after_weekly_reset(self):
        old=self.admit()
        MemberToken.objects.filter(pk=self.token.pk).update(cost_limit_cny=Decimal('.01'))
        # Fill the remaining Key allowance with several pending calls.
        while True:
            try:self.admit()
            except RelayError:break
        reset_budget('user:'+str(self.member.pk),'week')
        response=self.request_chat()
        self.assertEqual(response.status_code,429)
        self.assertEqual(response.json()['error']['code'],'key_quota_exceeded')
        self.assertEqual(Decimal(visible_budget(self.member)['member_week']['remaining_points']),1000)
        self.assertGreater(Decimal(self.get_api('/v1/key').json()['quota']['reserved_cny']),0)

    def test_usage_is_limited_to_current_key_and_does_not_expose_prompts(self):
        call=self.admit();settle(call,COUNTS)
        second=create_token(self.member,'other-key')
        response=self.client.get('/v1/usage',HTTP_AUTHORIZATION='Bearer '+second)
        self.assertEqual(response.json()['data'],[])
        own=self.get_api('/v1/usage').json()
        self.assertEqual(len(own['data']),1)
        self.assertNotIn('messages',own['data'][0]);self.assertNotIn('synthetic-supplier-key',json.dumps(own))
        self.assertEqual(self.get_api('/v1/usage?call_id=invalid').status_code,400)

    def test_read_queries_do_not_occupy_or_require_inference_slots(self):
        from .rate_limits import gate
        with gate(self.member,self.token),gate(self.member,self.token):
            for path in ('/v1/models','/v1/key','/v1/usage'):
                self.assertEqual(self.get_api(path).status_code,200)
            self.assertEqual(self.request_chat().status_code,429)
        self.assertFalse(Call.objects.exists())

    def test_invalid_requests_never_reach_supplier_or_reserve_cost(self):
        cases=[{'stream':'yes'}, {'temperature':True}, {'n':2}, {'max_tokens':True},
               {'max_tokens':0}, {'max_tokens':64,'max_completion_tokens':64}, {'unknown':1},
               {'messages':[{'role':'assistant','content':None}]},
               {'messages':[{'role':'tool','content':'orphan','tool_call_id':'x'}]},
               {'messages':[{'role':'user','content':[{'type':'image_url','image_url':{'url':'https://example.com/x.jpg'}}]}]},
               {'messages':[{'role':'user','content':'hello','_images':['data:image/jpeg;base64,xxx']}]},
               {'stream_options':{'include_usage':'yes'}}, {'tools':[{'type':'function','function':{'name':'bad name','parameters':{}}}]}]
        with patch('aihub.service.invoke') as supplier:
            for item in cases:
                data={'model':self.alias,'messages':[{'role':'user','content':'hello'}],'max_tokens':64,**item}
                with self.subTest(item=item):self.assertEqual(self.request_chat(data).status_code,400)
        supplier.assert_not_called();self.assertFalse(Call.objects.exists())

    def test_nonfinite_and_oversize_json_rejected_without_charge(self):
        with override_settings(WORKBENCH_RELAY_MAX_REQUEST_BYTES=220000):
            for body,status in [('{"model":"'+self.alias+'","temperature":NaN}',400),('x'*220001,413)]:
                response=self.client.post('/v1/chat/completions',body,content_type='application/json',HTTP_AUTHORIZATION='Bearer '+self.secret)
                self.assertEqual(response.status_code,status)
        self.assertFalse(Call.objects.exists())

    def test_tool_result_round_trip_and_strict_definition(self):
        payload={'model':self.alias,'messages':[{'role':'user','content':'test'},
            {'role':'assistant','content':None,'tool_calls':[{'id':'call_a','type':'function','function':{'name':'lookup','arguments':'{"q":"hello"}'}}]},
            {'role':'tool','tool_call_id':'call_a','content':'found'}],
            'tools':[{'type':'function','function':{'name':'lookup','parameters':{'type':'object','properties':{}},'strict':True}}],
            'tool_choice':{'type':'function','function':{'name':'lookup'}},'max_tokens':64}
        with patch('aihub.service.invoke',return_value=self.result()) as supplier:
            response=self.request_chat(payload)
        self.assertEqual(response.status_code,200,response.content)
        self.assertTrue(supplier.call_args.args[3][0]['function']['strict'])
        payload['messages'][1]['tool_calls'][0]['function']['arguments']='{"x":NaN}'
        self.assertEqual(self.request_chat(payload).status_code,400)

    def test_native_protocol_unsupported_options_are_explicit(self):
        self.provider.protocol='anthropic';self.provider.save()
        with self.assertRaises(RelayError):chat_payload({'messages':[{'role':'user','content':'hello'}],'response_format':{'type':'json_object'}},self.model)

    def test_unknown_supplier_result_has_lookup_id_and_no_retry(self):
        from .network import TransportError
        with patch('aihub.service.invoke',side_effect=TransportError('read_timeout',uncertain=True)):
            response=self.request_chat()
        self.assertEqual(response.status_code,502,response.content)
        self.assertEqual(response['x-should-retry'],'false')
        data=response.json()['error'];self.assertEqual(data['code'],'upstream_result_unknown')
        self.assertEqual(response['X-Request-ID'],data['call_id'])
        self.assertEqual(self.get_api('/v1/usage?call_id='+data['call_id']).json()['data'][0]['status'],'unknown')

    def test_streaming_http_keeps_team_scope_and_settles_once(self):
        events=[{'choices':[{'index':0,'delta':{'role':'assistant','content':'hello back'},'finish_reason':None}]},
                {'choices':[{'index':0,'delta':{},'finish_reason':'stop'}]},
                {'choices':[],'usage':{'prompt_tokens':1000,'completion_tokens':500,'total_tokens':1500}}]
        def frames(*args,**kwargs):yield from events
        with patch('aihub.gateway.json_events',side_effect=frames):
            response=self.request_chat({'model':self.alias,'messages':[{'role':'user','content':'hello'}],
                'max_tokens':64,'stream':True,'stream_options':{'include_usage':True}})
            self.assertEqual(response.status_code,200)
            body=b''.join(response.streaming_content).decode()
        self.assertIn('chat.completion.chunk',body);self.assertIn('data: [DONE]',body)
        call=Call.objects.get();self.assertEqual(call.status,'success')
        self.assertEqual(call.api_token_id,self.token.pk);self.assertEqual(call.cost_cny,Decimal('.002'))
        self.assertFalse(BudgetWeek.objects.exclude(reserved=0).exists())


@tag('sqlite-file')
class RelayConcurrencyTests(RelayFixture, TransactionTestCase):
    def workers(self, *jobs):
        workspace=Workspace.objects.get(pk=self.token.workspace_id)
        barrier=threading.Barrier(len(jobs))
        def run(job):
            try:
                with scope(workspace):
                    barrier.wait(timeout=10)
                    return job()
            finally:connections.close_all()
        with ThreadPoolExecutor(max_workers=len(jobs)) as executor:
            futures=[executor.submit(run,job) for job in jobs]
            return [future.result(timeout=30) for future in futures]

    def test_parallel_key_admission_cannot_exceed_cap(self):
        # One reservation fits, two do not; all writes must roll back on refusal.
        self.price.input_rate=30;self.price.output_rate=30;self.price.save()
        first=self.admit();one=first.reserved_cny;settle(first,None,'failed')
        cap=(one*Decimal('1.5')).quantize(Decimal('.01'))
        self.assertLess(one,cap);self.assertLess(cap,one*2)
        MemberToken.objects.filter(pk=self.token.pk).update(cost_limit_cny=cap)
        def admission():
            try:return self.admit().pk
            except RelayError as error:return error.api_code
        values=self.workers(admission,admission)
        self.assertEqual(values.count('key_quota_exceeded'),1)
        self.assertEqual(Call.objects.filter(status='running').count(),1)
        self.assertLessEqual(sum(Call.objects.filter(status='running').values_list('reserved_cny',flat=True)),cap)

    def test_parallel_duplicate_settlement_only_charges_once(self):
        call=self.admit()
        self.workers(lambda:settle(call,COUNTS),lambda:settle(call,COUNTS))
        for model,period in ((BudgetWeek,{'week':week_now()}),(BudgetMonth,{'month':month_now()})):
            bucket=model.objects.get(scope='user:'+str(self.member.pk),**period)
            self.assertEqual(bucket.spent,Decimal('.002'));self.assertEqual(bucket.reserved,0)

    def test_parallel_reset_and_old_settlement_restore_full_allowance(self):
        old=self.admit()
        self.workers(lambda:reset_budget('user:'+str(self.member.pk),'week'),lambda:settle(old,COUNTS))
        value=visible_budget(self.member)['member_week']
        self.assertEqual(Decimal(value['remaining_points']),1000)
        self.assertEqual(Decimal(value['reserved_points']),0)
        self.assertEqual(Call.objects.get(pk=old.pk).cost_cny,Decimal('.002'))

    def test_parallel_card_redemption_starts_only_one_new_generation(self):
        from .models import ResetCard, QuotaReset
        self.admit()
        issue(self.owner,str(self.member.pk),'week',1,7,uuid.uuid4())
        card=ResetCard.objects.get(user=self.member)
        values=self.workers(lambda:redeem(self.member,card.pk),lambda:redeem(self.member,card.pk))
        self.assertEqual(values.count(True),1);self.assertEqual(values.count(False),1)
        self.assertEqual(QuotaReset.objects.filter(card=card).count(),1)
        bucket=BudgetWeek.objects.get(scope='user:'+str(self.member.pk),week=week_now())
        self.assertEqual(bucket.generation,1);self.assertEqual(bucket.reserved,0)

    def test_parallel_member_admission_cannot_overdraw_base(self):
        self.price.input_rate=30;self.price.output_rate=30;self.price.save()
        first=self.admit(token=False);one=first.reserved_cny;settle(first,None,'failed')
        cap=(one*Decimal('1.5')).quantize(Decimal('.01'))
        self.assertLess(one,cap);self.assertLess(cap,one*2)
        self.config.default_weekly_limit=cap;self.config.save(update_fields=['default_weekly_limit'])
        from django.core.exceptions import ValidationError
        def admission():
            try:return self.admit(token=False).pk
            except ValidationError:return 'insufficient'
        values=self.workers(admission,admission)
        self.assertEqual(values.count('insufficient'),1)
        bucket=BudgetWeek.objects.get(scope='user:'+str(self.member.pk),week=week_now())
        self.assertLessEqual(bucket.reserved,cap)
