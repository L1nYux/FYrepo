import os
import re
from pathlib import Path
from datetime import timedelta
from unittest.mock import patch
from django.contrib.auth.models import User
from django.core import mail
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone
from .models import EmailVerificationCode as Code
from .email_binding import SESSION_KEY
from .tests import WorkbenchTestCase


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class BindingTests(WorkbenchTestCase):
    def setUp(self):
        super().setUp(); self.client.force_login(self.dev); self.url=reverse('profile')

    def send(self,email='new@example.com'):
        return self.client.post(self.url,{'action':'email_send','email':email})

    def code(self):
        return re.search(r'\b[0-9]{6}\b',mail.outbox[-1].body).group()

    def verify(self,code=None,client=None):
        return (client or self.client).post(self.url,{'action':'email_verify','code':code or self.code()})

    def test_bind_only_after_verification(self):
        self.send('NEW@EXAMPLE.COM'); self.dev.refresh_from_db(); self.assertEqual(self.dev.email,'')
        self.assertEqual(mail.outbox[-1].to,['new@example.com'])
        self.assertContains(self.client.get(self.url),'验证并绑定邮箱')
        self.assertRedirects(self.verify(),self.url)
        self.dev.refresh_from_db(); self.assertEqual(self.dev.email,'new@example.com')
        self.assertNotIn(SESSION_KEY,self.client.session);self.assertFalse(Code.objects.get().is_usable)
        self.assertTrue(self.client.get('/desktop/api/status/').json()['hasEmail'])

    def test_profile_post_cannot_bypass_code(self):
        self.client.post(self.url,{'action':'profile','first_name':'Changed','email':'bypass@example.com'})
        self.dev.refresh_from_db(); self.assertEqual(self.dev.first_name,'Changed'); self.assertEqual(self.dev.email,'')

    def test_change_preserves_old_mailbox_until_confirmed(self):
        self.dev.email='old@example.com';self.dev.save(update_fields=['email'])
        reset,_=Code.issue(self.dev,self.dev.email)
        self.send();self.dev.refresh_from_db();self.assertEqual(self.dev.email,'old@example.com')
        self.verify();self.dev.refresh_from_db();self.assertEqual(self.dev.email,'new@example.com')
        reset.refresh_from_db();self.assertIsNotNone(reset.used_at)

    def test_code_bound_to_browser_and_user(self):
        self.send();other=Client();other.force_login(self.dev)
        self.assertContains(self.verify(client=other),'验证码已失效')
        other.force_login(self.outsider);self.verify(client=other)
        self.dev.refresh_from_db();self.assertEqual(self.dev.email,'')
        self.verify();self.dev.refresh_from_db();self.assertEqual(self.dev.email,'new@example.com')

    def test_reset_code_cannot_bind(self):
        self.send();_,reset=Code.issue(self.dev,'old@example.com')
        self.assertContains(self.verify(reset),'验证码不正确')
        self.dev.refresh_from_db();self.assertEqual(self.dev.email,'')

    def test_wrong_attempts_and_expiry(self):
        self.send();wrong='000000' if self.code()!='000000' else '111111'
        for _ in range(5):self.verify(wrong)
        self.assertNotIn(SESSION_KEY,self.client.session);self.assertFalse(Code.objects.get().is_usable)
        self.dev.refresh_from_db();self.assertEqual(self.dev.email,'')

    def test_expired_code(self):
        self.send();Code.objects.update(expires_at=timezone.now()-timedelta(seconds=1))
        self.assertContains(self.verify(),'验证码已失效')

    def test_cooldown_and_hourly_cap(self):
        self.send();self.assertContains(self.send(),'秒后再发送');self.assertEqual(len(mail.outbox),1)
        for _ in range(4):Code.issue(self.dev,'new@example.com',Code.BIND)
        Code.objects.update(created_at=timezone.now()-timedelta(seconds=61))
        self.assertContains(self.send(),'发送过于频繁');self.assertEqual(len(mail.outbox),1)

    def test_duplicate_mailbox_on_send_and_confirmation(self):
        self.outsider.email='taken@example.com';self.outsider.save(update_fields=['email'])
        self.assertContains(self.send('taken@example.com'),'已被其他账号使用')
        self.send();self.outsider.email='new@example.com';self.outsider.save(update_fields=['email'])
        self.assertContains(self.verify(),'已被其他账号使用');self.dev.refresh_from_db();self.assertEqual(self.dev.email,'')

    def test_mail_failure_leaves_old_mailbox_and_no_usable_code(self):
        with patch('core.email_binding.send_mail',side_effect=RuntimeError('test mail failure')):
            self.assertContains(self.send(),'邮件暂时未能发送')
        self.dev.refresh_from_db();self.assertEqual(self.dev.email,'');self.assertFalse(Code.objects.get().is_usable)

    def test_other_tab_mailbox_change_invalidates_challenge(self):
        self.send();self.dev.email='changed@example.com';self.dev.save(update_fields=['email'])
        self.assertContains(self.verify(),'验证码已失效')
        self.dev.refresh_from_db();self.assertEqual(self.dev.email,'changed@example.com')

    def test_cancel_and_single_use(self):
        self.send();code=self.code();self.client.post(self.url,{'action':'email_cancel'})
        self.assertContains(self.verify(code),'验证码已失效');self.assertFalse(Code.objects.get().is_usable)

    def test_normal_member_and_csrf_required(self):
        self.client.force_login(self.outsider);self.assertEqual(self.send().status_code,302)
        other=Client(enforce_csrf_checks=True);other.force_login(self.outsider)
        self.assertEqual(other.post(self.url,{'action':'email_send','email':'x@example.com'}).status_code,403)

    def test_capture_binding_pages(self):
        target=os.environ.get('WORKBENCH_CAPTURE_UI')
        if not target:return
        folder=Path(target);folder.mkdir(parents=True,exist_ok=True)
        (folder/'binding-start.html').write_bytes(self.client.get(self.url).content)
        self.send();(folder/'binding-code.html').write_bytes(self.client.get(self.url).content)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class SteppedRecoveryTests(WorkbenchTestCase):
    def setUp(self):
        super().setUp();self.dev.email='dev@example.com';self.dev.save(update_fields=['email'])
        self.url=reverse('password_reset')

    def start(self):
        self.client.post(self.url,{'action':'send','identity':'dev'})
        code=re.search(r'\b[0-9]{6}\b',mail.outbox[-1].body).group()
        return self.client.post(self.url,{'action':'verify','code':code})

    def reset(self,password='fresh-pass-9921!'):
        return self.client.post(self.url,{'action':'reset','new_password1':password,'new_password2':password})

    def test_three_steps_and_password_not_needed_before_code(self):
        self.assertRedirects(self.start(),self.url)
        page=self.client.get(self.url);self.assertContains(page,'保存新密码');self.assertNotContains(page,'name="code"')
        self.assertContains(self.reset(),'密码已重置');self.dev.refresh_from_db();self.assertTrue(self.dev.check_password('fresh-pass-9921!'))
        self.assertContains(self.reset(),'请先获取验证码')

    def test_password_validation_retains_verified_step(self):
        self.start();self.assertIn('new_password2',self.reset('123').context['password_form'].errors)
        self.assertContains(self.client.get(self.url),'保存新密码');self.assertContains(self.reset(),'密码已重置')

    def test_ticket_invalidated_by_mailbox_or_password_change(self):
        self.start();self.dev.set_password('changed-password-883');self.dev.save(update_fields=['password'])
        self.assertContains(self.reset(),'验证已失效');self.dev.refresh_from_db();self.assertTrue(self.dev.check_password('changed-password-883'))

    def test_captured_verified_mobile_page(self):
        if os.environ.get('WORKBENCH_CAPTURE_UI'):
            self.start();(Path(os.environ['WORKBENCH_CAPTURE_UI'])/'recovery-verified.html').write_bytes(self.client.get(self.url).content)

    def test_old_link_routes_use_code_flow(self):
        self.assertRedirects(self.client.get(reverse('password_reset_done')),self.url)
