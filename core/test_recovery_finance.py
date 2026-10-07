import re
from datetime import timedelta
from unittest import mock
from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone
from .tests import WorkbenchTestCase
from .models import EmailVerificationCode, ExpenseClaim, FinanceEntry
from .recovery import SESSION_KEY

@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class RecoveryTests(WorkbenchTestCase):
    def setUp(self):
        super().setUp(); cache.clear(); mail.outbox=[]
        self.dev.email='dev@example.com'; self.dev.save(update_fields=['email'])
        self.url=reverse('password_reset')

    def send(self, identity='dev@example.com', client=None):
        return (client or self.client).post(self.url, {'action':'send','identity':identity})

    def code(self):
        return re.search(r'\b\d{6}\b', mail.outbox[-1].body).group()

    def reset(self, code, client=None, password='updated-pass-9812!'):
        return (client or self.client).post(self.url, {'action':'reset','code':code,
            'new_password1':password,'new_password2':password})

    def test_anonymous_same_page_flow(self):
        self.assertContains(self.client.get(self.url),'工作台号或邮箱')
        self.assertRedirects(self.send(),self.url)
        self.assertEqual(mail.outbox[0].to,['dev@example.com'])
        self.assertContains(self.client.get(self.url),'验证验证码')
        self.assertContains(self.reset(self.code()),'密码已重置')
        self.dev.refresh_from_db(); self.assertTrue(self.dev.check_password('updated-pass-9812!'))
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_username_supported(self):
        self.send('dev'); self.assertEqual(len(mail.outbox),1)

    def test_email_case_supported(self):
        self.send('DEV@EXAMPLE.COM'); self.assertEqual(len(mail.outbox),1)

    def test_unknown_identity_has_same_response(self):
        self.assertRedirects(self.send('missing@example.com'), self.url, fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox),0)
        page=self.client.get(self.url)
        self.assertContains(page,'如果该账户已绑定可用邮箱')
        self.assertContains(page,'验证验证码')

    def test_no_email_account_gets_no_email(self):
        self.send('other');self.assertEqual(len(mail.outbox),0)

    def test_inactive_gets_no_email(self):
        self.dev.is_active=False;self.dev.save(update_fields=['is_active'])
        self.send(); self.assertEqual(len(mail.outbox),0)

    def test_signed_in_uses_own_email_and_keeps_session(self):
        self.client.force_login(self.dev)
        self.send('boss'); self.assertEqual(mail.outbox[0].to,['dev@example.com'])
        self.reset(self.code());self.assertEqual(self.client.get(reverse('dashboard')).status_code,200)

    def test_signed_in_without_email_can_bind(self):
        self.client.force_login(self.outsider)
        page=self.client.get(self.url)
        self.assertContains(page,'去绑定邮箱');self.assertNotContains(page,'发送验证码')

    def test_wrong_code_does_not_change_password(self):
        self.send();code='000000' if self.code()!='000000' else '111111'
        self.assertContains(self.reset(code),'验证码不正确')
        self.dev.refresh_from_db();self.assertTrue(self.dev.check_password('verify-only-12345'))

    def test_five_attempts_exhaust_code(self):
        self.send();code='000000' if self.code()!='000000' else '111111'
        for _ in range(5):self.reset(code)
        self.assertNotIn(SESSION_KEY,self.client.session)
        self.assertFalse(EmailVerificationCode.objects.get().is_usable)

    def test_expired_code(self):
        self.send();code=self.code()
        EmailVerificationCode.objects.update(expires_at=timezone.now()-timedelta(seconds=1))
        self.assertContains(self.reset(code),'验证码已失效')

    def test_new_session_cannot_use_another_challenge(self):
        self.send();self.assertContains(self.reset(self.code(),client=Client()),'请先获取验证码')

    def test_single_use(self):
        self.send();code=self.code();self.reset(code)
        self.assertContains(self.reset(code),'请先获取验证码')

    def test_changed_email_invalidates_code(self):
        self.send();code=self.code();self.dev.email='new@example.com';self.dev.save(update_fields=['email'])
        self.reset(code);self.dev.refresh_from_db();self.assertTrue(self.dev.check_password('verify-only-12345'))

    def test_password_validation_does_not_consume_attempt(self):
        self.send();self.reset(self.code(),password='123')
        self.assertEqual(EmailVerificationCode.objects.get().attempts,0)

    def test_account_specific_validation_keeps_code_usable(self):
        self.dev.username='ResearchTeamMember9812';self.dev.save(update_fields=['username'])
        self.send();code=self.code()
        self.assertContains(self.reset(code,password='ResearchTeamMember9812'), '相似')
        item=EmailVerificationCode.objects.get()
        self.assertEqual(item.attempts,0);self.assertIsNone(item.used_at)
        self.assertContains(self.reset(code),'密码已重置')

    def test_non_ascii_digits_are_not_accepted_as_code(self):
        self.send();self.assertContains(self.reset('１２３４５６'),'请输入 6 位数字验证码')
        self.assertEqual(EmailVerificationCode.objects.get().attempts,0)

    def test_resend_cooldown(self):
        self.send();self.send();self.assertEqual(len(mail.outbox),1)

    def test_old_sessions_invalidated(self):
        other=Client();other.force_login(self.dev)
        self.send();self.reset(self.code())
        self.assertEqual(other.get(reverse('dashboard')).status_code,302)

    def test_send_failure_is_not_500(self):
        self.client.force_login(self.dev)
        with mock.patch('core.recovery.send_mail', side_effect=RuntimeError('mail unavailable')):
            page=self.send(client=self.client)
        self.assertEqual(page.status_code,302);self.assertEqual(EmailVerificationCode.objects.count(),0)
        self.assertContains(self.client.get(self.url),'邮件暂时未能发送')

    def test_legacy_code_paths_point_to_unified_page(self):
        for name in ['password_code_reset','password_code_send','password_code_new_password']:
            self.assertRedirects(self.client.get(reverse(name)),self.url)

    def test_mobile_page_is_standalone(self):
        page=self.client.get(self.url)
        self.assertContains(page,'viewport-fit=cover');self.assertNotContains(page,'global-topbar')
        self.send();self.assertContains(self.client.get(self.url),'autocomplete="one-time-code"')

    def test_empty_email_profile_save_and_desktop_status(self):
        self.client.force_login(self.outsider)
        self.assertFalse(self.client.get('/desktop/api/status/').json()['hasEmail'])
        self.assertRedirects(self.client.post(reverse('profile'),{'action':'profile','first_name':'同学','email':''}),reverse('profile'))
        self.assertRedirects(self.client.post(reverse('profile'),{'action':'profile','first_name':'同学','email':'other@example.com'}),reverse('profile'))
        self.assertFalse(self.client.get('/desktop/api/status/').json()['hasEmail'])

    def test_email_login_supported(self):
        from .models import MemberProfile
        MemberProfile.objects.update_or_create(user=self.dev,defaults={'legacy_login_allowed':True})
        response=self.client.post('/desktop/api/login/', {'username':'DEV@EXAMPLE.COM','password':'verify-only-12345'},content_type='application/json')
        self.assertEqual(response.status_code,200);self.assertTrue(response.json()['authenticated'])

    def test_capture_actual_pages_for_renderer_debug(self):
        import os
        from pathlib import Path
        target=os.environ.get('WORKBENCH_CAPTURE_UI')
        if not target:return
        path=Path(target);path.mkdir(parents=True,exist_ok=True)
        self.send();(path/'recovery.html').write_bytes(self.client.get(self.url).content)
        self.client.force_login(self.dev);self.client.get('/desktop/api/status/')
        self.client.post(reverse('profile'),{'action':'profile','first_name':'Debug','email':'dev@example.com'})
        (path/'profile.html').write_bytes(self.client.get(reverse('profile')).content)
        (path/'workspace.html').write_bytes(self.client.get(reverse('workspace_home')).content)

class FinanceDeletionTests(WorkbenchTestCase):
    def setUp(self):
        super().setUp();self.client.force_login(self.admin)
        self.entry=FinanceEntry.objects.create(kind='expense',amount='20.00',occurred_on=timezone.localdate(),memo='误填账目',created_by=self.admin,project=self.project)

    def archive(self):
        return self.client.post(reverse('finance_archive',args=[self.entry.pk]))

    def test_archive_and_restore_updates_balance(self):
        self.assertEqual(self.client.get(reverse('finance_list')).context['outflow'],20)
        self.archive();self.assertEqual(self.client.get(reverse('finance_list')).context['outflow'],0)
        self.assertContains(self.client.get(reverse('recycle_bin')),'误填账目')
        self.client.post(reverse('restore',args=['finance',self.entry.pk]))
        self.assertEqual(self.client.get(reverse('finance_list')).context['outflow'],20)

    def test_only_admin_can_delete_ledger(self):
        self.client.force_login(self.dev);self.assertEqual(self.archive().status_code,403)

    def test_archive_is_post_only(self):
        self.assertEqual(self.client.get(reverse('finance_archive',args=[self.entry.pk])).status_code,405)

    def test_archived_entry_cannot_be_edited(self):
        self.archive();self.assertEqual(self.client.get(reverse('finance_edit',args=[self.entry.pk])).status_code,404)

    def test_signed_confirmation_required(self):
        self.archive();url=reverse('permanently_delete',args=['finance',self.entry.pk])
        page=self.client.get(url);self.assertContains(page,'data-confirm-delete')
        self.client.post(url,{'action':'delete','confirm':'yes'})
        self.assertTrue(FinanceEntry.objects.filter(pk=self.entry.pk).exists())
        page=self.client.get(url)
        self.client.post(url,{'action':'delete','confirm':'yes','confirmation':page.context['confirmation']})
        self.assertFalse(FinanceEntry.objects.filter(pk=self.entry.pk).exists())

    def test_approved_claim_follows_entry_and_deletes_together(self):
        claim=ExpenseClaim.objects.create(applicant=self.dev,amount=20,occurred_on=timezone.localdate(),memo='误填申请',status=ExpenseClaim.APPROVED,entry=self.entry)
        self.archive();claim.refresh_from_db();self.assertIsNotNone(claim.archived_at)
        url=reverse('permanently_delete',args=['finance',self.entry.pk]);page=self.client.get(url)
        self.client.post(url,{'action':'delete','confirm':'yes','confirmation':page.context['confirmation']})
        self.assertFalse(ExpenseClaim.objects.filter(pk=claim.pk).exists())

    def test_own_pending_claim_can_be_deleted_and_restored(self):
        claim=ExpenseClaim.objects.create(applicant=self.dev,amount=10,occurred_on=timezone.localdate(),memo='错单')
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.post(reverse('claim_archive',args=[claim.pk])).status_code,403)
        self.client.force_login(self.dev)
        self.assertEqual(self.client.post(reverse('claim_archive',args=[claim.pk])).status_code,302)
        self.assertEqual(self.client.post(reverse('restore',args=['claim',claim.pk])).status_code,302)
        claim.refresh_from_db();self.assertIsNone(claim.archived_at)

    def test_deleted_claim_cannot_be_approved(self):
        claim=ExpenseClaim.objects.create(applicant=self.dev,amount=10,occurred_on=timezone.localdate(),memo='错单',archived_at=timezone.now())
        self.assertEqual(self.client.post(reverse('claim_review',args=[claim.pk]),{'decision':'approve'}).status_code,404)

    def test_permanent_delete_get_never_mutates(self):
        self.archive();self.client.get(reverse('permanently_delete',args=['finance',self.entry.pk]))
        self.assertTrue(FinanceEntry.objects.filter(pk=self.entry.pk).exists())

    def test_project_cost_updates_after_delete(self):
        from .views import project_cost
        self.assertEqual(project_cost(self.project)['cost_spent'],20)
        self.archive();self.assertEqual(project_cost(self.project)['cost_spent'],0)

    def test_capture_actual_preview_for_renderer_debug(self):
        import os
        from pathlib import Path
        target=os.environ.get('WORKBENCH_CAPTURE_UI')
        if target:
            Path(target).mkdir(parents=True, exist_ok=True)
            self.archive()
            page=self.client.get(reverse('permanently_delete',args=['finance',self.entry.pk]))
            Path(target,'delete.html').write_bytes(page.content)
