"""Regression paths from GitHub issue #9, including archive/restore payment reuse."""
from decimal import Decimal
from unittest.mock import patch
from django.test import TestCase
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone
from . import test_collaboration_v4
from .models import ExpenseClaim,FinanceEntry,TeamMembership
from .funding_claims import submit
from .tenancy import scope
from aihub.models import Call,PointGrant,PoolSettings


class FundingIntegrityTests(TestCase):
    setUp=test_collaboration_v4.CollaborationV4Tests.setUp
    pool=test_collaboration_v4.CollaborationV4Tests.pool

    def usage_claim(self,kind='cash'):
        TeamMembership.objects.get_or_create(team=self.team,user=self.person,defaults={'role':'member'})
        model,price=self.pool(self.personal,self.person)
        with scope(self.personal):
            call=Call.objects.create(user=self.person,model=model,price=price,status='success',cost_cny=Decimal('1.20'),budget_month=timezone.localdate().replace(day=1))
        return call,self.claim(call,kind)

    def claim(self,call,kind='cash'):
        with scope(self.teamspace):
            return submit(ExpenseClaim(applicant=self.person,settlement_kind=kind,amount=Decimal('1.20'),occurred_on=timezone.localdate(),memo='成果经费'),[call])

    def approve(self,claim):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(reverse('claim_review',args=[claim.pk]),{'decision':'approve'}).status_code,302)

    def archive(self,claim):
        self.client.force_login(self.person)
        self.assertEqual(self.client.post(reverse('claim_archive',args=[claim.pk])).status_code,302)

    def test_archived_claim_cannot_restore_after_usage_paid_by_other_claim(self):
        call,first=self.usage_claim()
        self.archive(first)
        second=self.claim(call)
        self.approve(second)
        self.client.force_login(self.person)
        response=self.client.post(reverse('restore',args=['claim',first.pk]))
        self.assertEqual(response.status_code,302)
        first.refresh_from_db();self.assertIsNotNone(first.archived_at)
        self.assertFalse(first.usage_receipts.get().active)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(reverse('claim_review',args=[first.pk]),{'decision':'approve'}).status_code,404)
        self.assertEqual(FinanceEntry.all_objects.filter(workspace=self.teamspace,kind='reimburse').count(),1)

    def test_restore_reactivates_unclaimed_receipt_and_allows_one_payment(self):
        _call,claim=self.usage_claim()
        self.archive(claim)
        self.assertEqual(self.client.post(reverse('restore',args=['claim',claim.pk])).status_code,302)
        claim.refresh_from_db();self.assertIsNone(claim.archived_at)
        self.assertTrue(claim.usage_receipts.get().active)
        self.approve(claim);self.approve(claim)
        self.assertEqual(FinanceEntry.all_objects.filter(workspace=self.teamspace,kind='reimburse').count(),1)

    def test_recycle_bin_keeps_claim_ownership_without_changing_session(self):
        _call,claim=self.usage_claim()
        self.archive(claim)
        response=self.client.post(reverse('restore',args=['claim',claim.pk]))
        self.assertIn('ownership='+str(self.teamspace.pk),response['Location'])
        self.assertEqual(self.client.session['workbench-space'],'personal')
        self.assertEqual(self.client.get(response['Location']).status_code,200)

    def test_foreign_team_cannot_restore_or_delete_claim(self):
        _call,claim=self.usage_claim()
        self.archive(claim)
        self.client.force_login(self.stranger)
        for route in ('restore','permanently_delete'):
            self.assertEqual(self.client.post(reverse(route,args=['claim',claim.pk])).status_code,404)
        claim.refresh_from_db();self.assertIsNotNone(claim.archived_at)

    def test_inactive_receipt_blocks_cash_payment_even_for_legacy_restored_claim(self):
        _call,claim=self.usage_claim()
        claim.usage_receipts.update(active=False)
        self.approve(claim)
        claim.refresh_from_db();self.assertEqual(claim.status,ExpenseClaim.PENDING)
        self.assertFalse(FinanceEntry.all_objects.filter(workspace=self.teamspace,kind='reimburse').exists())

    def test_recycle_preview_explains_existing_receipt_delete_protection(self):
        _call,claim=self.usage_claim();self.archive(claim)
        self.client.force_login(self.owner)
        url=reverse('permanently_delete',args=['claim',claim.pk])
        preview=self.client.get(url)
        self.assertContains(preview,'仍被 API 用量凭证引用')
        self.assertNotContains(preview,'value="delete"')
        response=self.client.post(url,{'confirmation':preview.context['confirmation'],'confirm':'yes','action':'delete'},follow=True)
        self.assertContains(response,'仍被 API 用量凭证引用')
        self.assertTrue(ExpenseClaim.all_objects.filter(pk=claim.pk).exists())
        self.assertEqual(claim.usage_receipts.count(),1)

    def test_inactive_receipt_blocks_quota_credit(self):
        _call,claim=self.usage_claim('api_quota')
        claim.usage_receipts.update(active=False)
        self.approve(claim)
        claim.refresh_from_db();self.assertEqual(claim.status,ExpenseClaim.PENDING)
        self.assertFalse(PointGrant.all_objects.filter(workspace=self.teamspace).exists())

    def test_quota_reimbursement_without_usage_is_rejected_by_form_and_service(self):
        from .forms import ClaimForm
        with scope(self.teamspace):
            form=ClaimForm({'settlement_kind':'api_quota','amount':'1.20','memo':'补发'},user=self.person)
            self.assertFalse(form.is_valid());self.assertIn('usage_calls',form.errors)
            with self.assertRaises(ValidationError):
                submit(ExpenseClaim(applicant=self.person,settlement_kind='api_quota',amount=Decimal('1.20'),
                    occurred_on=timezone.localdate(),memo='补发'),[])
        self.assertFalse(ExpenseClaim.all_objects.filter(workspace=self.teamspace).exists())

    def test_legacy_receiptless_reimbursement_cannot_issue_points(self):
        with scope(self.teamspace):
            claim=ExpenseClaim.objects.create(applicant=self.owner,settlement_kind='api_quota',amount=Decimal('1.20'),
                occurred_on=timezone.localdate(),memo='旧申请')
        self.approve(claim)
        claim.refresh_from_db();self.assertEqual(claim.status,ExpenseClaim.PENDING)
        self.assertFalse(PointGrant.all_objects.filter(workspace=self.teamspace).exists())

    def test_receipted_quota_approval_credits_once_without_cash_entry(self):
        _call,claim=self.usage_claim('api_quota')
        self.pool(self.teamspace,self.owner)
        from aihub.service import allowance
        with scope(self.teamspace):
            member=allowance(self.person);before=member.extra_balance
        self.approve(claim);self.approve(claim)
        member.refresh_from_db();self.assertEqual(member.extra_balance,before+claim.amount)
        self.assertEqual(PointGrant.all_objects.filter(workspace=self.teamspace).count(),1)
        self.assertFalse(FinanceEntry.all_objects.filter(workspace=self.teamspace,kind='reimburse').exists())

    def test_pool_prepayment_stays_separate_from_claim_form(self):
        from .forms import ClaimForm
        with scope(self.teamspace):
            form=ClaimForm(user=self.person)
        self.assertEqual({value for value,_label in form.fields['settlement_kind'].choices},{'cash','api_quota'})

    def test_limit_form_locks_current_space_row_instead_of_fixed_pool(self):
        from aihub.forms import SettingsForm
        with scope(self.personal):PoolSettings.objects.create(owner=self.person)
        with scope(self.teamspace):
            settings=PoolSettings.objects.create(owner=self.owner)
            self.assertNotEqual(settings.pk,1)
            form=SettingsForm({'enabled':'on','weekly_limit':'100','default_weekly_limit':'100','monthly_limit':'200','default_member_limit':'200','max_call_cost':'50'},instance=settings)
            self.assertTrue(form.is_valid(),form.errors)
            with patch.object(PoolSettings.objects,'filter',wraps=PoolSettings.objects.filter) as query:
                form.save()
            query.assert_any_call(pk=settings.pk)
