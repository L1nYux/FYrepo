from datetime import date
from decimal import Decimal
import os
from pathlib import Path

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import FinanceEntry, Workspace, Team, TeamMembership, MemberProfile, Project
from .tenancy import scope


class PersonalAreaTests(TestCase):
    def setUp(self):
        with scope(None, http=True):
            self.person = User.objects.create_user('personal-person')
            self.other = User.objects.create_user('personal-other')
            for person in (self.person, self.other): MemberProfile.objects.create(user=person)
        self.personal = Workspace.objects.create(kind='personal', owner=self.person)
        self.other_space = Workspace.objects.create(kind='personal', owner=self.other)
        self.team = Team.objects.create(name='团队账本', owner=self.other)
        self.team_space = Workspace.objects.create(kind='team', team=self.team)
        TeamMembership.objects.create(team=self.team, user=self.other, role='owner')
        TeamMembership.objects.create(team=self.team, user=self.person, role='member')
        with scope(self.personal):
            self.entry = FinanceEntry.objects.create(kind='expense', amount='12.50', occurred_on=date.today(), memo='午餐', created_by=self.person)
        with scope(self.other_space):
            self.other_entry = FinanceEntry.objects.create(kind='income', amount='900', occurred_on=date.today(), memo='他人私账', created_by=self.other)
        with scope(self.team_space):
            self.team_entry = FinanceEntry.objects.create(kind='income', amount='700', occurred_on=date.today(), memo='团队私账', created_by=self.other)
            self.project = Project.objects.create(name='团队项目', owner=self.other, created_by=self.other)
        self.client.force_login(self.person)
        session=self.client.session; session['workbench-space']='team:'+str(self.team.pk); session.save()

    def test_me_uses_personal_scope_without_changing_session(self):
        result = self.client.get(reverse('me_home'))
        self.assertContains(result, '个人事务')
        self.assertContains(result, '我的 API')
        self.assertNotContains(result, '团队公告')
        self.assertNotContains(result, 'sidebar-projects')
        self.assertEqual(result.context['current_workspace'].pk, self.personal.pk)
        self.assertEqual(self.client.session['workbench-space'], 'team:'+str(self.team.pk))

    def test_personal_ledger_is_private_and_has_no_approvals(self):
        result=self.client.get(reverse('me_ledger')+'?ownership='+str(self.team_space.pk))
        self.assertContains(result,'午餐')
        for text in ('他人私账','团队私账','待审报销','经费申请','账本归属','记账人'):
            self.assertNotContains(result,text)
        self.assertEqual(result.context['balance'],Decimal('-12.50'))

    def test_legacy_personal_finance_redirects_to_simple_ledger(self):
        self.assertRedirects(self.client.get(reverse('finance_list')), reverse('me_ledger'))

    def test_amount_only_entry_and_delete(self):
        result=self.client.post(reverse('me_ledger_new'),{'kind':'income','amount':'60'})
        self.assertRedirects(result, reverse('me_ledger'))
        entry=FinanceEntry.all_objects.get(workspace=self.personal,kind='income')
        self.assertEqual(entry.memo,'')
        self.assertEqual(entry.occurred_on,date.today())
        self.assertEqual(entry.created_by,self.person)
        result=self.client.post(reverse('me_ledger_edit',args=[entry.pk]),{'kind':'expense','amount':'20','memo':'交通'})
        self.assertRedirects(result,reverse('me_ledger'))
        entry.refresh_from_db();self.assertEqual(entry.kind,'expense')
        self.assertRedirects(self.client.post(reverse('me_ledger_archive',args=[entry.pk])),reverse('me_ledger'))
        entry.refresh_from_db();self.assertIsNotNone(entry.archived_at)
        self.assertEqual(self.client.get(reverse('me_ledger_edit',args=[entry.pk])).status_code,404)

    def test_personal_form_rejects_team_types_and_team_projects(self):
        for values in ({'kind':'reimburse','amount':'5'}, {'kind':'expense','amount':'5','project':self.project.pk}, {'kind':'expense','amount':'0'}):
            result=self.client.post(reverse('me_ledger_new'),values)
            self.assertEqual(result.status_code,200)
            self.assertTrue(result.context['form'].errors)
        self.assertEqual(FinanceEntry.all_objects.filter(workspace=self.personal).count(),1)

    def test_me_edit_and_delete_cannot_access_team_or_other_person(self):
        for entry in (self.other_entry,self.team_entry):
            self.assertEqual(self.client.get(reverse('me_ledger_edit',args=[entry.pk])).status_code,404)
            self.assertEqual(self.client.post(reverse('me_ledger_archive',args=[entry.pk])).status_code,404)
            entry.refresh_from_db();self.assertIsNone(entry.archived_at)

    def test_existing_personal_special_type_can_be_edited(self):
        FinanceEntry.all_objects.filter(pk=self.entry.pk).update(kind='api')
        result=self.client.post(reverse('me_ledger_edit',args=[self.entry.pk]),{'kind':'api','amount':'12.50','memo':'历史 API 支出'})
        self.assertRedirects(result,reverse('me_ledger'))

    def test_team_finance_keeps_approval_workflow(self):
        self.assertContains(self.client.get(reverse('finance_teams')),'团队账本')
        self.client.force_login(self.other)
        result=self.client.get(reverse('finance_list')+'?ownership='+str(self.team_space.pk))
        self.assertContains(result,'待审报销')
        self.assertNotContains(result,'午餐')
        self.assertEqual(result.context['income'],Decimal('700'))

    def test_personal_cannot_submit_organizational_claim(self):
        result=self.client.post(reverse('claim_new'),{'amount':'5','memo':'不应提交'})
        self.assertEqual(result.status_code,403)

    def test_personal_api_links_cannot_be_redirected_to_team(self):
        self.assertRedirects(self.client.get(reverse('me_usage')+'?ownership='+str(self.team_space.pk)),reverse('me_api'))
        self.assertRedirects(self.client.get(reverse('me_connections')),reverse('me_api')+'?tab=connections')

    def test_contact_categories_and_capture(self):
        pages={'me':reverse('me_home'),'ledger':reverse('me_ledger'),'ledgerform':reverse('me_ledger_new'),'contacts':reverse('messages_social')+'?tab=friends'}
        for name,url in pages.items():
            result=self.client.get(url);self.assertEqual(result.status_code,200)
            if name=='contacts':
                self.assertContains(result,'class="contact-category"',count=4)
                self.assertNotContains(result,'class="communication-categories"')
            if os.environ.get('WORKBENCH_CAPTURE_UI'):
                folder=Path(os.environ['WORKBENCH_CAPTURE_UI']);folder.mkdir(parents=True,exist_ok=True)
                (folder/f'v4-{name}.html').write_bytes(result.content)
