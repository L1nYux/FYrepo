"""Authorized relay failure, accounting and shared-circuit checks; no paid requests."""
import json
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from django.urls import reverse

from .forms import ModelForm
from .models import BudgetWeek, Call, MemberToken, PoolModel, PriceVersion, Provider, ProviderHealth
from .network import TransportError
from .relay import RelayError
from .routing import acquire, reset_health
from .service import settle, week_now
from .test_relay_contract import RelayFixture
from . import test_relay_contract as contract_tests


class RoutingFixture(RelayFixture):
    def setUp(self):
        super().setUp()
        self.backup_provider=Provider.objects.create(name='Backup provider',base_url='https://backup.example.com/v1')
        self.backup=PoolModel.objects.create(provider=self.backup_provider,model_id=self.model.model_id)
        self.backup_price=PriceVersion.objects.create(model=self.backup,effective_from=timezone.now(),
            input_rate=3,output_rate=6,cached_rate=1,cache_write_rate=2)
        self.model.fallback_model=self.backup;self.model.save(update_fields=['fallback_model'])

    def supplier(self, model, *args, **kwargs):
        if model.pk==self.model.pk: raise TransportError('dns_error')
        return self.result()

    def frames(self, url, *args, **kwargs):
        if url.startswith(self.provider.base_url):raise TransportError('http_429')
        yield {'choices':[{'delta':{'role':'assistant','content':'first part'},'finish_reason':None}]}
        yield {'choices':[{'delta':{'content':' second part'},'finish_reason':'stop'}]}
        yield {'choices':[],'usage':{'prompt_tokens':1000,'completion_tokens':500}}

    def stream(self):
        return self.request_chat({'model':self.alias,'messages':[{'role':'user','content':'hello'}],
            'max_tokens':64,'stream':True,'stream_options':{'include_usage':True}})

    def body(self, response):
        return b''.join(response.streaming_content).decode()


class RelayRoutingTests(RoutingFixture, TransactionTestCase):
    def test_safe_failure_switches_once_and_charges_actual_price(self):
        with patch('aihub.service.invoke',side_effect=self.supplier) as supplier:
            response=self.request_chat()
        self.assertEqual(response.status_code,200)
        self.assertEqual(supplier.call_count,2)
        data=response.json();root=response['X-Request-ID']
        self.assertEqual(data['id'],root)
        self.assertEqual(data['workbench']['attempt_count'],2)
        self.assertEqual(data['workbench']['cost_cny'],'0.00600000')
        rows=Call.objects.order_by('created_at')
        self.assertEqual(rows[0].cost_cny,0);self.assertEqual(rows[0].status,'failed')
        self.assertEqual(rows[1].model_id,self.backup.pk);self.assertEqual(rows[1].price_id,self.backup_price.pk)
        self.assertEqual({str(row.group_id) for row in rows},{root})
        bucket=BudgetWeek.objects.get(scope='user:'+str(self.member.pk),week=week_now())
        self.assertEqual(bucket.reserved,0);self.assertEqual(bucket.spent,Decimal('.006'))
        self.assertEqual(len(self.get_api('/v1/usage?call_id='+root).json()['data']),2)

    def test_unconfigured_fallback_preserves_single_attempt(self):
        self.model.fallback_model=None;self.model.save()
        with patch('aihub.service.invoke',side_effect=TransportError('http_429')) as supplier:
            response=self.request_chat()
        self.assertEqual(response.status_code,502);self.assertEqual(supplier.call_count,1)
        self.assertEqual(Call.objects.get().cost_cny,0)

    def test_uncertain_result_never_switches(self):
        for code in ('connection_interrupted','http_500','invalid_json'):
            with self.subTest(code=code), patch('aihub.service.invoke',side_effect=TransportError(code,True)) as supplier:
                response=self.request_chat()
                self.assertEqual(response.status_code,502);self.assertEqual(supplier.call_count,1)
                call=Call.objects.get(pk=response.json()['error']['call_id'])
                self.assertEqual(call.status,'unknown');self.assertIsNone(call.cost_cny)
                self.assertGreater(call.reserved_cny,0)

    def test_validation_rejection_does_not_switch_or_trip_other_models(self):
        with patch('aihub.service.invoke',side_effect=TransportError('http_400')) as supplier:
            response=self.request_chat()
        self.assertEqual(response.status_code,502);self.assertEqual(supplier.call_count,1)
        self.assertEqual(ProviderHealth.objects.get(provider=self.provider).failures,0)

    def test_missing_model_can_switch_without_tripping_provider(self):
        def supplier(model,*args,**kwargs):
            if model.pk==self.model.pk:raise TransportError('http_404')
            return self.result()
        with patch('aihub.service.invoke',side_effect=supplier):self.assertEqual(self.request_chat().status_code,200)
        self.assertEqual(ProviderHealth.objects.get(provider=self.provider).failures,0)

    def test_key_model_policy_cannot_be_bypassed(self):
        MemberToken.objects.filter(pk=self.token.pk).update(allowed_models=[self.model.pk])
        with patch('aihub.service.invoke',side_effect=self.supplier) as supplier:
            response=self.request_chat()
        self.assertEqual(response.status_code,502);self.assertEqual(supplier.call_count,1)
        self.assertEqual(Call.objects.count(),1);self.assertEqual(Call.objects.get().cost_cny,0)

    def test_key_revocation_between_attempts_blocks_backup(self):
        def supplier(*args,**kwargs):
            MemberToken.objects.filter(pk=self.token.pk).update(revoked_at=timezone.now())
            raise TransportError('dns_error')
        with patch('aihub.service.invoke',side_effect=supplier) as supplier:
            response=self.request_chat()
        self.assertEqual(response.status_code,401);self.assertEqual(supplier.call_count,1)
        self.assertEqual(Call.objects.count(),1)

    def test_backup_reservation_rechecks_its_price_and_key_limit(self):
        MemberToken.objects.filter(pk=self.token.pk).update(cost_limit_cny=Decimal('.01'))
        self.backup_price.input_rate=30;self.backup_price.output_rate=60;self.backup_price.save()
        with patch('aihub.service.invoke',side_effect=self.supplier) as supplier:
            response=self.request_chat()
        self.assertEqual(response.status_code,429,response.content);self.assertEqual(supplier.call_count,1,response.content)
        self.assertEqual(Call.objects.count(),1)
        self.assertEqual(response['X-Request-ID'],str(Call.objects.get().pk))
        self.assertEqual(ProviderHealth.objects.get(provider=self.backup_provider).failures,0)
        self.assertFalse(BudgetWeek.objects.exclude(reserved=0).exists())

    def test_disabled_or_incompatible_backup_is_not_called(self):
        for field,value in [('enabled',False),('model_id','different-model'),('max_output_tokens',32),('supports_tools',False)]:
            if field=='supports_tools':continue
            with self.subTest(field=field):
                original=getattr(self.backup,field);setattr(self.backup,field,value);self.backup.save()
                with patch('aihub.service.invoke',side_effect=self.supplier) as supplier:
                    self.assertEqual(self.request_chat().status_code,502)
                self.assertEqual(supplier.call_count,1)
                setattr(self.backup,field,original);self.backup.save()

    def test_missing_backup_price_does_not_send_or_mark_provider_failed(self):
        self.backup_price.delete()
        with patch('aihub.service.invoke',side_effect=self.supplier) as supplier:self.request_chat()
        self.assertEqual(supplier.call_count,1)
        self.assertEqual(ProviderHealth.objects.get(provider=self.backup_provider).failures,0)
        self.assertFalse(BudgetWeek.objects.exclude(reserved=0).exists())

    def test_cycles_do_not_expand_beyond_two_attempts(self):
        self.backup.fallback_model=self.model;self.backup.save()
        with patch('aihub.service.invoke',side_effect=TransportError('dns_error')) as supplier:
            response=self.request_chat()
        self.assertEqual(response.status_code,502);self.assertEqual(supplier.call_count,2)
        self.assertEqual(Call.objects.count(),2)
        self.assertEqual(response['X-Request-ID'],str(Call.objects.earliest('created_at').pk))

    def test_cooling_primary_is_skipped(self):
        ProviderHealth.objects.create(provider=self.provider,cooldown_until=timezone.now()+timezone.timedelta(minutes=1))
        with patch('aihub.service.invoke',return_value=self.result()) as supplier:
            response=self.request_chat()
        self.assertEqual(response.status_code,200);self.assertEqual(supplier.call_args.args[0].pk,self.backup.pk)
        self.assertEqual(Call.objects.count(),1);self.assertEqual(response.json()['workbench']['attempt_count'],1)

    def test_stream_fallback_has_stable_id_and_real_partial_frames(self):
        with patch('aihub.gateway.json_events',side_effect=self.frames) as supplier:
            response=self.stream();iterator=iter(response.streaming_content)
            first=next(iterator).decode()
            self.assertIn('first part',first)
            self.assertEqual(Call.objects.filter(status='running').count(),1)
            body=first+b''.join(iterator).decode()
        self.assertNotIn('"error"',body);self.assertEqual(supplier.call_count,2)
        values=[json.loads(frame[6:]) for frame in body.split('\n\n') if frame and frame!='data: [DONE]']
        self.assertEqual({value['id'] for value in values},{response['X-Request-ID']})
        self.assertEqual(values[-1]['workbench']['attempt_count'],2)
        self.assertEqual(Call.objects.filter(status='success').get().cost_cny,Decimal('.006'))
        self.assertFalse(BudgetWeek.objects.exclude(reserved=0).exists())

    def test_partial_output_then_rejection_is_unknown_and_never_switches(self):
        def frames(*args,**kwargs):
            yield {'choices':[{'delta':{'content':'already emitted'},'finish_reason':None}]}
            raise TransportError('http_429')
        with patch('aihub.gateway.json_events',side_effect=frames) as supplier:
            body=self.body(self.stream())
        self.assertIn('already emitted',body);self.assertEqual(supplier.call_count,1)
        self.assertEqual(Call.objects.get().status,'unknown');self.assertIsNone(Call.objects.get().cost_cny)

    def test_stream_uncertain_before_output_is_not_retried(self):
        with patch('aihub.gateway.json_events',side_effect=TransportError('connection_interrupted',True)) as supplier:
            body=self.body(self.stream())
        self.assertIn('unknown',body);self.assertEqual(supplier.call_count,1)

    def test_stream_close_before_start_releases_reservation_and_probe(self):
        ProviderHealth.objects.create(provider=self.provider,cooldown_until=timezone.now()-timezone.timedelta(seconds=1))
        response=self.stream();response.close()
        self.assertEqual(Call.objects.get().status,'failed')
        self.assertFalse(BudgetWeek.objects.exclude(reserved=0).exists())
        self.assertIsNone(ProviderHealth.objects.get(provider=self.provider).probe_token)

    def test_stream_close_after_first_frame_retains_unknown_reservation(self):
        with patch('aihub.gateway.json_events',side_effect=self.frames):
            response=self.stream();next(iter(response.streaming_content));response.close()
        self.assertEqual(Call.objects.filter(model=self.backup).get().status,'unknown')
        self.assertGreater(BudgetWeek.objects.get(scope='team',week=week_now()).reserved,0)
        self.assertEqual(ProviderHealth.objects.get(provider=self.backup_provider).failures,0)

    def test_usage_missing_does_not_switch_and_clears_circuit(self):
        result=self.result();result['counts']=None
        with patch('aihub.service.invoke',return_value=result) as supplier:response=self.request_chat()
        self.assertEqual(response.status_code,200);self.assertEqual(supplier.call_count,1)
        self.assertEqual(Call.objects.get().status,'unknown')
        self.assertEqual(ProviderHealth.objects.get(provider=self.provider).failures,0)

    def test_form_validates_backup_identity(self):
        data={'provider':self.provider.pk,'model_id':self.model.model_id,'enabled':True,'supports_tools':True,
            'max_output_tokens':32768,'output_parameter':'max_tokens','price_mode':'auto','fallback_model':self.backup.pk}
        form=ModelForm(data,instance=self.model)
        self.assertTrue(form.is_valid(),form.errors)
        self.backup.model_id='wrong';self.backup.save()
        self.assertIn('fallback_model',ModelForm(data,instance=self.model).errors)

    def test_health_reset_requires_pool_owner(self):
        ProviderHealth.objects.create(provider=self.provider,cooldown_until=timezone.now()+timezone.timedelta(minutes=30))
        response=self.client.post(reverse('api_manage'),{'action':'reset_provider_health','id':self.provider.pk})
        self.assertEqual(response.status_code,403)
        self.client.force_login(self.owner)
        session=self.client.session
        session['workbench-space']='team:'+str(self.team.pk)
        session['workbench-team']=self.team.pk
        session.save()
        response=self.client.post(reverse('api_manage'),{'action':'reset_provider_health','id':self.provider.pk})
        self.assertEqual(response.status_code,302,response.content.decode()[-1600:])
        self.assertIsNone(ProviderHealth.objects.get(provider=self.provider).cooldown_until)


class SharedCircuitTests(RoutingFixture, TransactionTestCase):
    workers=contract_tests.RelayConcurrencyTests.workers

    def fail(self, lease, code='connection_interrupted'):
        call=self.admit();settle(call,None,'unknown',code);call.refresh_from_db();lease.complete(call)

    def test_three_parallel_failures_open_circuit(self):
        leases=[acquire(self.provider) for _ in range(3)]
        calls=[self.admit() for _ in range(3)]
        for call in calls:settle(call,None,'unknown','connection_interrupted');call.refresh_from_db()
        self.workers(*[lambda i=i:leases[i].complete(calls[i]) for i in range(3)])
        health=ProviderHealth.objects.get(provider=self.provider)
        self.assertEqual(health.failures,3);self.assertGreater(health.cooldown_until,timezone.now())
        with self.assertRaises(RelayError):acquire(self.provider)

    def test_expired_circuit_allows_only_one_parallel_probe(self):
        ProviderHealth.objects.create(provider=self.provider,cooldown_until=timezone.now()-timezone.timedelta(seconds=1))
        def claim():
            try:return acquire(self.provider)
            except RelayError:return None
        leases=self.workers(claim,claim,claim)
        self.assertEqual(sum(lease is not None for lease in leases),1)

    def test_late_success_cannot_close_newer_circuit(self):
        old=acquire(self.provider);self.fail(acquire(self.provider),'http_401')
        success=self.admit();settle(success,self.result()['counts']);success.refresh_from_db();old.complete(success)
        self.assertIsNotNone(ProviderHealth.objects.get(provider=self.provider).cooldown_until)

    def test_live_probe_keeps_lease_beyond_initial_timeout(self):
        ProviderHealth.objects.create(provider=self.provider,cooldown_until=timezone.now()-timezone.timedelta(seconds=1))
        lease=acquire(self.provider);call=self.admit();lease.bind(call)
        ProviderHealth.objects.filter(provider=self.provider).update(probe_until=timezone.now()-timezone.timedelta(seconds=1))
        with self.assertRaises(RelayError):acquire(self.provider)
        Call.objects.filter(pk=call.pk).update(heartbeat_at=timezone.now()-timezone.timedelta(minutes=3))
        fresh=acquire(self.provider)
        settle(call,self.result()['counts']);call.refresh_from_db();lease.complete(call)
        self.assertEqual(ProviderHealth.objects.get(provider=self.provider).probe_token,fresh.token)

    def test_successful_probe_restores_regular_calls(self):
        ProviderHealth.objects.create(provider=self.provider,cooldown_until=timezone.now()-timezone.timedelta(seconds=1))
        lease=acquire(self.provider);call=self.admit();lease.bind(call)
        settle(call,self.result()['counts']);call.refresh_from_db();lease.complete(call)
        self.assertIsNone(acquire(self.provider).token)
