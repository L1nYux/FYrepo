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
        self.assertContains(result, '我的人才资料')
        self.assertNotContains(result, '我的 API');self.assertNotContains(result,'个人记账')
        self.assertNotContains(result, '团队公告')
        self.assertNotContains(result, 'sidebar-projects')
        self.assertEqual(result.context['current_workspace'].pk, self.personal.pk)
        self.assertEqual(self.client.session['workbench-space'], 'team:'+str(self.team.pk))

    def test_talent_editing_belongs_to_me_and_legacy_links_preserve_posts(self):
        url=reverse('talent_profile')
        self.assertEqual(url,'/me/talent/')
        result=self.client.get(url)
        self.assertEqual(result.status_code,200)
        self.assertTrue(result.context['is_me'])
        self.assertFalse(result.context['is_discover'])
        self.assertEqual(result.context['current_workspace'].pk,self.personal.pk)
        self.assertEqual(self.client.session['workbench-space'],'team:'+str(self.team.pk))
        for legacy in ('legacy_talent_profile','applicant_resume'):
            result=self.client.get(reverse(legacy))
            self.assertEqual(result.status_code,307)
            self.assertEqual(result['Location'],url)
            result=self.client.post(reverse(legacy),{'introduction':'旧页面填写的资料'},follow=True)
            self.assertIn((url,307),result.redirect_chain)
            from .models import ApplicantProfile
            self.assertEqual(ApplicantProfile.objects.get(user=self.person).introduction,'旧页面填写的资料')
        discovery=self.client.get(reverse('talent_market'))
        self.assertNotContains(discovery,'>我的人才资料</a>')

    def test_retired_ledger_routes_preserve_all_existing_data(self):
        before=list(FinanceEntry.all_objects.order_by('pk').values())
        routes=[reverse('me_ledger'),reverse('me_ledger_new')]
        for entry in (self.entry,self.other_entry,self.team_entry):
            routes.extend([reverse('me_ledger_edit',args=[entry.pk]),reverse('me_ledger_archive',args=[entry.pk])])
        for url in routes:
            self.assertRedirects(self.client.get(url),reverse('me_home'))
            self.assertRedirects(self.client.post(url,{'kind':'income','amount':'60','memo':'ignored'}),reverse('me_home'))
        self.assertEqual(list(FinanceEntry.all_objects.order_by('pk').values()),before)

    def test_legacy_personal_finance_redirects_through_retired_ledger(self):
        result=self.client.get(reverse('finance_list'),follow=True)
        self.assertEqual(result.redirect_chain,[(reverse('me_ledger'),302),(reverse('me_home'),302)])

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

    def test_legacy_api_links_enter_authorized_team_pool(self):
        target=reverse('api_pool')+'?ownership='+str(self.team_space.pk)
        for name in ('me_api','me_usage','me_connections'):
            response=self.client.get(reverse(name),follow=True)
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.redirect_chain[-1],(target,302))
            self.assertEqual(response.context['current_workspace'].pk,self.team_space.pk)
        foreign=Workspace.objects.create(kind='team',team=Team.objects.create(name='Foreign',owner=self.other))
        self.assertEqual(self.client.get(reverse('me_api')+'?funding='+str(foreign.pk)).status_code,403)

    def test_contact_categories_and_capture(self):
        pages={'me':reverse('me_home'),'contacts':reverse('messages_social')+'?tab=friends'}
        for name,url in pages.items():
            result=self.client.get(url);self.assertEqual(result.status_code,200)
            if name=='contacts':
                self.assertContains(result,'class="contact-category"',count=4)
                self.assertNotContains(result,'class="communication-categories"')
            if os.environ.get('WORKBENCH_CAPTURE_UI'):
                folder=Path(os.environ['WORKBENCH_CAPTURE_UI']);folder.mkdir(parents=True,exist_ok=True)
                (folder/f'v4-{name}.html').write_bytes(result.content)
