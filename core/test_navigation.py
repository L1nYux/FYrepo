import os
from pathlib import Path
from django.urls import reverse
from .tests import WorkbenchTestCase
from .models import TeamContact
from .navigation import workspace_return_path

class WorkspaceNavigationTests(WorkbenchTestCase):
    def setUp(self):
        super().setUp();self.client.force_login(self.admin)

    def test_contact_save_stays_on_internal_edit_page(self):
        for desktop in (False,True):
            if desktop:self.client.get('/desktop/api/status/')
            response=self.client.post(reverse('contact_edit'),{'email':'team@example.com','phone':'123','description':'合作说明'},follow=True)
            self.assertEqual(response.redirect_chain,[(reverse('contact_edit'),302)])
            self.assertContains(response,'团队联系方式已保存。')
            self.assertContains(response,'team@example.com')
            self.assertTrue(response.context['shell_enabled'])
            self.assertNotContains(response,'下载桌面版')
            self.assertContains(response,'data-public-preview')
            self.assertContains(response,'target="_blank"')
        self.assertEqual(TeamContact.objects.get(pk=1).email,'team@example.com')

    def test_invalid_contact_preserves_errors_and_permissions(self):
        response=self.client.post(reverse('contact_edit'),{'email':'invalid','phone':'123'})
        self.assertEqual(response.status_code,200);self.assertTrue(response.context['form'].errors)
        self.assertContains(response,'value="123"')
        self.client.force_login(self.dev);self.assertEqual(self.client.get(reverse('contact_edit')).status_code,403)

    def test_authenticated_recovery_retains_workspace(self):
        self.admin.email='boss@example.com';self.admin.save(update_fields=['email'])
        for desktop in (False,True):
            if desktop:self.client.get('/desktop/api/status/')
            response=self.client.get(reverse('password_reset'))
            self.assertTrue(response.context['shell_enabled']);self.assertTemplateUsed(response,'core/recovery_workspace.html')
            self.assertContains(response,'recovery-workspace.css');self.assertContains(response,'返回密码与安全')
            self.assertNotContains(response,'recovery-brand');self.assertNotContains(response,'下载桌面版')

    def test_anonymous_recovery_keeps_standalone_layout(self):
        self.client.logout();response=self.client.get(reverse('password_reset'))
        self.assertFalse(response.context['shell_enabled']);self.assertContains(response,'recovery.css')
        self.assertNotContains(response,'recovery-workspace.css')

    def test_public_site_remains_explicit_visitor_destination(self):
        response=self.client.get(reverse('public_members'))
        self.assertFalse(response.context['shell_enabled']);self.assertContains(response,'下载桌面版')

    def test_return_paths_reject_public_external_and_action_login(self):
        for value in ['/','/contact/','/public/members/','/showcase/','/about/','//example.com/','/\\example.com/','/%2fexample.com/','/account/login/','/missing/',None,[]]:
            self.assertIsNone(workspace_return_path(value),repr(value))
        for value in ['/workspace/','/tasks/'+str(self.child.pk)+'/?tab=all#results','/manage/contact/','/account/public/']:
            self.assertEqual(workspace_return_path(value),value)

    def test_capture_internal_pages(self):
        target=os.environ.get('WORKBENCH_CAPTURE_UI')
        if not target:return
        path=Path(target);path.mkdir(parents=True,exist_ok=True)
        self.admin.email='boss@example.com';self.admin.save(update_fields=['email']);self.client.get('/desktop/api/status/')
        (path/'contact.html').write_bytes(self.client.get(reverse('contact_edit')).content)
        (path/'recovery-bound.html').write_bytes(self.client.get(reverse('password_reset')).content)
