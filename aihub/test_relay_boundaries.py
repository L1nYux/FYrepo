"""Synthetic upstream events: no supplier credentials or paid requests."""
import json
import uuid
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.utils import timezone

from . import tests as pool_regression
from .gateway import ChatStream
from .models import BudgetWeek, Call, QuotaReset, ResetCard
from .network import TransportError
from .quota_cards import issue, redeem, revoke
from .service import settle, week_now


class RelayBoundaryTests(TestCase):
    def setUp(self):
        pool_regression.PoolRegressionTests.setUp(self)
        for target in ('aihub.service.provider_key', 'aihub.gateway.provider_key'):
            mocked = patch(target, return_value='synthetic-key')
            mocked.start()
            self.addCleanup(mocked.stop)

    def stream(self, include_usage=True):
        return ChatStream(self.member, self.model, [{'role':'user','content':'hello'}],
                          [], 64, {}, 'test-alias', include_usage)

    def events(self, chunks):
        def upstream():
            try:
                for item in chunks:
                    if isinstance(item, Exception): raise item
                    yield item
            finally:
                self.upstream_closed = True
        self.upstream_closed = False
        return upstream()

    def chunks(self, usage=True):
        chunks = [
            {'id':'synthetic-request','choices':[{'delta':{'role':'assistant','content':'答'}}]},
            {'choices':[{'delta':{'content':'案'},'finish_reason':'stop'}]},
        ]
        if usage:
            chunks.append({'choices':[], 'usage':{'prompt_tokens':1000,'completion_tokens':500}})
        return chunks

    def decoded(self, frames):
        return [json.loads(frame[6:].strip()) for frame in frames if frame.strip()!='data: [DONE]']

    def test_finished_stream_settles_once_and_preserves_usage_frame(self):
        stream=self.stream()
        with patch('aihub.gateway.json_events',return_value=self.events(self.chunks())) as upstream:
            frames=list(stream)
        stream.close(); stream.close()
        stream.call.refresh_from_db()
        self.assertEqual(stream.call.status,'success')
        self.assertEqual(stream.call.cost_cny,Decimal('.002'))
        self.assertEqual(upstream.call_count,1)
        self.assertTrue(self.upstream_closed)
        self.assertEqual(frames[-1],'data: [DONE]\n\n')
        usage=self.decoded(frames)[-1]
        self.assertEqual(usage['choices'],[])
        self.assertEqual(usage['usage']['total_tokens'],1500)
        self.assertEqual(usage['workbench']['status'],'success')
        bucket=BudgetWeek.objects.get(scope='user:'+str(self.member.pk),week=week_now())
        self.assertEqual(bucket.spent,Decimal('.002')); self.assertEqual(bucket.reserved,0)

    def test_close_before_first_chunk_releases_reservation_without_upstream(self):
        stream=self.stream()
        with patch('aihub.gateway.json_events') as upstream:
            stream.close();stream.close()
        upstream.assert_not_called()
        stream.call.refresh_from_db()
        self.assertEqual(stream.call.status,'failed')
        self.assertEqual(stream.call.error_code,'stream_not_started')
        self.assertFalse(BudgetWeek.objects.exclude(reserved=0).exists())

    def test_close_after_partial_chunk_keeps_uncertain_reservation_without_retry(self):
        stream=self.stream()
        with patch('aihub.gateway.json_events',return_value=self.events(self.chunks())) as upstream:
            next(stream); stream.close(); stream.close()
        stream.call.refresh_from_db()
        self.assertEqual(stream.call.status,'unknown')
        self.assertEqual(stream.call.error_code,'stream_disconnected')
        self.assertEqual(upstream.call_count,1); self.assertTrue(self.upstream_closed)
        bucket=BudgetWeek.objects.get(scope='user:'+str(self.member.pk),week=week_now())
        self.assertEqual(bucket.reserved,stream.call.reserved_cny)

    def test_connection_failure_releases_reserved_quota(self):
        stream=self.stream()
        with patch('aihub.gateway.json_events',return_value=self.events([TransportError('connect_failed',False)])):
            frames=list(stream)
        stream.call.refresh_from_db()
        self.assertEqual(stream.call.status,'failed')
        self.assertFalse(BudgetWeek.objects.exclude(reserved=0).exists())
        self.assertEqual(self.decoded(frames)[0]['workbench']['status'],'failed')

    def test_missing_finish_keeps_uncertain_quota_and_reports_error(self):
        stream=self.stream()
        with patch('aihub.gateway.json_events',return_value=self.events(self.chunks()[:1])):
            frames=list(stream)
        stream.call.refresh_from_db()
        self.assertEqual(stream.call.status,'unknown')
        self.assertEqual(self.decoded(frames)[-1]['error']['type'],'incomplete_stream')

    def test_missing_usage_never_reports_a_zero_cost_success(self):
        stream=self.stream()
        with patch('aihub.gateway.json_events',return_value=self.events(self.chunks(usage=False))):
            frames=list(stream)
        stream.call.refresh_from_db()
        self.assertEqual(stream.call.status,'unknown')
        final=self.decoded(frames)[-1]
        self.assertIsNone(final['usage']);self.assertIsNone(final['workbench']['cost_cny'])
        self.assertEqual(final['workbench']['status'],'unknown')

    def test_fragmented_tool_calls_stay_valid_and_are_accounted_once(self):
        stream=self.stream()
        chunks=[
            {'choices':[{'delta':{'tool_calls':[{'index':0,'id':'call-1','type':'function','function':{'name':'read_','arguments':'{"id":'}}]}}]},
            {'choices':[{'delta':{'tool_calls':[{'index':0,'function':{'name':'record','arguments':'2}'}}]},'finish_reason':'tool_calls'}]},
            {'choices':[],'usage':{'prompt_tokens':3,'completion_tokens':4}},
        ]
        with patch('aihub.gateway.json_events',return_value=self.events(chunks)):
            frames=list(stream)
        stream.call.refresh_from_db()
        self.assertEqual(stream.call.status,'success')
        self.assertEqual(self.decoded(frames)[-2]['choices'][0]['finish_reason'],'tool_calls')
        self.assertEqual(stream.call.output_tokens,4)

    def test_usage_can_be_omitted_from_response_without_skipping_settlement(self):
        stream=self.stream(include_usage=False)
        with patch('aihub.gateway.json_events',return_value=self.events(self.chunks())):
            frames=list(stream)
        self.assertFalse(any('usage' in frame for frame in self.decoded(frames)))
        stream.call.refresh_from_db();self.assertEqual(stream.call.status,'success')


class ResetCardBoundaryTests(TestCase):
    def setUp(self):
        pool_regression.PoolRegressionTests.setUp(self)
        mocked=patch('aihub.service.provider_key',return_value='synthetic-key')
        mocked.start();self.addCleanup(mocked.stop)

    def card(self):
        issue(self.owner,str(self.member.pk),'week',1,7,uuid.uuid4())
        return ResetCard.objects.get(user=self.member)

    def spent(self):
        from .service import reserve
        call=reserve(self.member,self.model,[{'role':'user','content':'hello'}],[],64,'api',None,None,None)
        settle(call,None,'success',cost_override=Decimal('3'))
        return call

    def test_issue_retry_with_same_batch_has_no_duplicate_cards(self):
        batch=uuid.uuid4()
        self.assertEqual(issue(self.owner,str(self.member.pk),'week',2,7,batch),2)
        self.assertEqual(issue(self.owner,str(self.member.pk),'week',2,7,batch),0)
        self.assertEqual(ResetCard.objects.count(),2)
        with self.assertRaises(ValidationError):issue(self.owner,str(self.member.pk),'month',2,7,batch)

    def test_member_cannot_issue_or_revoke(self):
        with self.assertRaises(PermissionDenied):issue(self.member,str(self.member.pk),'week',1,7,uuid.uuid4())
        card=self.card()
        with self.assertRaises(PermissionDenied):revoke(self.member,card.pk)

    def test_no_spent_usage_does_not_consume_card(self):
        card=self.card()
        with self.assertRaises(ValidationError):redeem(self.member,card.pk)
        card.refresh_from_db();self.assertIsNone(card.used_at)
        self.assertFalse(QuotaReset.objects.exists())

    def test_redeem_once_restores_allowance_without_erasing_cost_history(self):
        call=self.spent();card=self.card()
        self.assertTrue(redeem(self.member,card.pk));self.assertFalse(redeem(self.member,card.pk))
        bucket=BudgetWeek.objects.get(scope='user:'+str(self.member.pk),week=week_now())
        self.assertEqual(bucket.spent,3);self.assertEqual(bucket.reset_credit,3)
        self.assertEqual(Call.objects.get(pk=call.pk).cost_cny,3)
        self.assertEqual(QuotaReset.objects.filter(card=card).count(),1)

    def test_old_pending_call_cannot_consume_redeemed_allowance(self):
        self.spent()
        from .service import reserve
        pending=reserve(self.member,self.model,[{'role':'user','content':'hello'}],[],64,'api',None,None,None)
        card=self.card();redeem(self.member,card.pk)
        bucket=BudgetWeek.objects.get(scope='user:'+str(self.member.pk),week=week_now())
        self.assertEqual(bucket.reserved,0)
        self.assertEqual(bucket.generation,1)
        settle(pending,{'input_tokens':1000,'output_tokens':500,'cached_tokens':0,'cache_write_tokens':0,'reasoning_tokens':0})
        bucket.refresh_from_db();self.assertEqual(bucket.spent-bucket.reset_credit,0)
        self.assertEqual(bucket.reserved,0)

    def test_other_member_expired_and_revoked_cards_cannot_redeem(self):
        self.spent();card=self.card()
        with self.assertRaises(ValidationError):redeem(self.admin,card.pk)
        ResetCard.objects.filter(pk=card.pk).update(expires_at=timezone.now()-timedelta(seconds=1))
        with self.assertRaises(ValidationError):redeem(self.member,card.pk)
        ResetCard.objects.filter(pk=card.pk).update(expires_at=timezone.now()+timedelta(days=1))
        self.assertEqual(revoke(self.owner,card.pk),1)
        with self.assertRaises(ValidationError):redeem(self.member,card.pk)
        self.assertFalse(QuotaReset.objects.exists())
