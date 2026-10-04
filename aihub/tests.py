import json
from decimal import Decimal
from unittest.mock import patch
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from .models import PoolSettings, Provider, PoolModel, PriceVersion, BudgetMonth, BudgetWeek, Call
from .permissions import visible_budget
from .service import reserve, settle, reset_budget, week_now, month_now
from .usage import dashboard


class PoolRegressionTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user('pool-owner',is_staff=True)
        self.admin = User.objects.create_user('other-admin',is_staff=True)
        self.member = User.objects.create_user('member')
        self.config = PoolSettings.objects.create(pk=1,owner=self.owner,weekly_limit=100,default_weekly_limit=20)
        self.provider = Provider.objects.create(name='Test provider',base_url='https://example.com/v1')
        self.model = PoolModel.objects.create(provider=self.provider,model_id='test-model')
        self.price = PriceVersion.objects.create(model=self.model,effective_from=timezone.now(),input_rate=1,
            output_rate=2,cached_rate=Decimal('.1'),cache_write_rate=Decimal('.5'))
        self.client.force_login(self.member)

    def reserve_call(self):
        with patch('aihub.service.provider_key',return_value='fake-test-key'):
            return reserve(self.member,self.model,[{'role':'user','content':'hello'}],[],64,'api',None,None,None)

    def test_pool_management_is_owner_only_including_other_admins(self):
        for user in (self.member,self.admin):
            self.client.force_login(user)
            self.assertEqual(self.client.get(reverse('api_manage')).status_code,403)
            self.assertEqual(self.client.post(reverse('api_discover'),json.dumps({}),content_type='application/json').status_code,403)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse('api_manage')).status_code,200)
        self.assertEqual(self.client.get(reverse('api_pool'),{'scope':'team'}).status_code,200)

    def test_member_cannot_see_team_usage_or_reset_budgets(self):
        response = self.client.get(reverse('api_pool'),{'scope':'team'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.context['scope'],'mine')
        self.assertNotContains(response,'API 池管理')
        self.assertEqual(self.client.post(reverse('api_pool'),{'action':'reset_budget','target':'team'}).status_code,403)
        value = visible_budget(self.member)
        self.assertNotIn('team',value)
        self.assertNotIn('team_week',value)
        self.assertIn('member_week',value)

    def test_catalog_hides_prices_and_keys_for_members(self):
        with patch('aihub.views.provider_key',return_value='fake-test-key'):
            data = self.client.get(reverse('api_catalog')).json()
        model = data['models'][0]
        self.assertNotIn('input_rate',model)
        self.assertNotIn('output_rate',model)
        self.assertNotIn('fake-test-key',str(data))

    def test_management_has_single_entry_and_consistent_tabs(self):
        self.client.force_login(self.owner)
        self.assertNotContains(self.client.get(reverse('workspace_home')),reverse('api_manage'))
        self.assertNotContains(self.client.get(reverse('workspace_home')),'进入项目管理')
        self.assertNotContains(self.client.get(reverse('ai_assistant')),reverse('api_manage'))
        self.assertContains(self.client.get(reverse('profile')),reverse('api_manage'),count=1)
        for response in (self.client.get(reverse('api_manage')),self.client.get(reverse('api_pool'),{'scope':'team'})):
            self.assertContains(response,'连接与模型')
            self.assertContains(response,'额度与用量')
        self.assertNotContains(self.client.get(reverse('api_pool')),'API 池管理')

    @override_settings(WORKBENCH_DESKTOP=True)
    def test_desktop_layout_keeps_team_management_and_personal_usage_separate(self):
        self.client.force_login(self.owner)
        team = self.client.get(reverse('api_pool'),{'scope':'team'})
        self.assertTrue(team.context['desktop_settings_page'])
        mine = self.client.get(reverse('api_pool'))
        self.assertFalse(mine.context['desktop_settings_page'])
        self.assertTrue(mine.context['is_personal_usage'])
        self.assertNotContains(mine,'<aside class="shell-sidebar"')

    def test_weekly_limit_rejection_rolls_back_all_reservations(self):
        self.config.default_weekly_limit=0
        self.config.save(update_fields=['default_weekly_limit'])
        with self.assertRaises(ValidationError): self.reserve_call()
        self.assertEqual(Call.objects.count(),0)
        self.assertFalse(BudgetWeek.objects.exclude(reserved=0).exists())
        self.assertFalse(BudgetMonth.objects.exclude(reserved=0).exists())

    def test_cost_settlement_is_idempotent_and_does_not_double_count_reasoning(self):
        call = self.reserve_call()
        counts = {'input_tokens':1000,'output_tokens':500,'cached_tokens':200,'cache_write_tokens':100,'reasoning_tokens':50}
        settle(call,counts); settle(call,counts)
        call.refresh_from_db()
        self.assertEqual(call.cost_cny,Decimal('.00177'))
        for Model, period in ((BudgetWeek,{'week':week_now()}),(BudgetMonth,{'month':month_now()})):
            for scope in ('team','user:'+str(self.member.pk)):
                row = Model.objects.get(scope=scope,**period)
                self.assertEqual(row.spent,Decimal('.00177'))
                self.assertEqual(row.reserved,0)

    def test_reset_preserves_real_spend_history_and_pending_reservations(self):
        completed = self.reserve_call(); settle(completed,None,'success',cost_override=Decimal('3'))
        pending = self.reserve_call(); settle(pending,None,'unknown')
        reset_budget('user:'+str(self.member.pk),'week')
        row = BudgetWeek.objects.get(scope='user:'+str(self.member.pk),week=week_now())
        self.assertEqual(row.spent,3)
        self.assertEqual(row.reset_credit,3)
        self.assertEqual(row.reserved,pending.reserved_cny)
        self.assertEqual(Call.objects.count(),2)
        self.assertEqual(visible_budget(self.member)['member_week']['spent'],'0.0000')

    def test_team_dashboard_cannot_be_requested_by_nonowner(self):
        call = self.reserve_call(); settle(call,None,'success',cost_override=Decimal('1'))
        value = dashboard(self.admin,team=True)
        self.assertEqual(value['total_calls'],0)
        owner_value = dashboard(self.owner,team=True)
        self.assertEqual(owner_value['total_calls'],1)

    def test_invalid_reset_period_is_rejected_without_writing_budget(self):
        with self.assertRaises(ValidationError): reset_budget('team','invalid')
        self.assertFalse(BudgetWeek.objects.exists())

    def test_invalid_reset_period_does_not_crash_either_management_page(self):
        self.client.force_login(self.owner)
        for name in ('api_pool','api_manage'):
            response = self.client.post(reverse(name),{'action':'reset_budget','target':'team','period':'invalid'},follow=True)
            self.assertEqual(response.status_code,200)
        self.assertFalse(BudgetWeek.objects.exists())

    def test_missing_reset_member_does_not_crash_either_management_page(self):
        self.client.force_login(self.owner)
        for name in ('api_pool','api_manage'):
            response = self.client.post(reverse(name),{'action':'reset_budget','target':'user'},follow=True)
            self.assertEqual(response.status_code,200)
            self.assertContains(response,'请选择有效成员。' if name=='api_pool' else '输入无效。')
        self.assertFalse(BudgetWeek.objects.exists())

    def test_disabled_model_cannot_be_saved_as_preference(self):
        self.model.enabled=False; self.model.save(update_fields=['enabled'])
        response = self.client.post(reverse('api_preferences'),json.dumps({'model':self.model.pk}),content_type='application/json')
        self.assertEqual(response.status_code,404)

    def test_malformed_json_is_rejected_without_any_model_call(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse('api_discover'),'{bad-json',content_type='application/json')
        self.assertEqual(response.status_code,400)
        self.assertEqual(Call.objects.count(),0)
