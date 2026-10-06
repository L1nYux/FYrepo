import json
import os
import re
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from aihub.models import MemberToken, PoolSettings
from .forms import RoleLoginForm
from .models import (Announcement, ChatMessage, Competition, Experiment, FinanceEntry,
                     Invite, MemberProfile, Project, PublicProfile, Task, TeamMembership)


class MemberManagementTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user('directory-admin', password='original-Q5-password', is_staff=True)
        self.member = User.objects.create_user('directory-member', password='original-Q5-password', first_name='实验成员')
        self.next = User.objects.create_user('directory-next', password='original-Q5-password')
        self.normal = User.objects.create_user('directory-normal', password='original-Q5-password')
        MemberProfile.objects.create(user=self.normal, tier='normal')
        PublicProfile.objects.create(user=self.member, display_name='公开昵称', research_area='机器学习', bio='公开简介', is_public=True)
        self.client.force_login(self.admin)

    def reset(self):
        with patch('core.member_management.secrets.token_urlsafe', return_value='fixture-temporary-Q5-only'):
            return self.client.post(reverse('member_reset_password', args=[self.member.pk]), {'confirm': 'reset'})

    def delete(self, **extra):
        return self.client.post(reverse('member_delete', args=[self.member.pk]), {'confirm_username': self.member.username, **extra})

    def test_directory_open_to_members_management_stays_admin_only(self):
        self.client.force_login(self.member)
        result = self.client.get(reverse('members'))
        self.assertContains(result, '成员资料库')
        self.assertNotContains(result, 'directory-normal')
        self.assertNotContains(result, '重置密码')
        for name in ('member_reset_password', 'member_delete'):
            self.assertEqual(self.client.post(reverse(name, args=[self.next.pk]), {'confirm': 'reset'}).status_code, 403)

    def test_directory_search_shared_name_and_area(self):
        for query in ('公开昵称', '机器学习', '实验成员', 'directory-member'):
            self.assertContains(self.client.get(reverse('members'), {'q': query}), 'directory-member')

    def test_directory_does_not_search_or_expose_private_profile(self):
        PublicProfile.objects.filter(user=self.member).update(is_public=False)
        for query in ('公开昵称', '机器学习'):
            self.assertNotContains(self.client.get(reverse('members'), {'q': query}), 'directory-member')
        self.assertNotContains(self.client.get(reverse('members')), '公开简介')

    def test_normal_account_cannot_open_internal_directory(self):
        self.client.force_login(self.normal)
        self.assertEqual(self.client.get(reverse('members'))['Location'], reverse('showcase'))

    def test_reset_without_email_only_displays_password_in_post_response(self):
        response = self.reset()
        self.assertContains(response, 'fixture-temporary-Q5-only')
        self.assertIn('no-store', response['Cache-Control'])
        self.assertNotIn('fixture-temporary-Q5-only', str(dict(self.client.session)))
        self.assertNotContains(self.client.get(reverse('member_reset_password', args=[self.member.pk])), 'fixture-temporary-Q5-only')
        self.member.refresh_from_db()
        self.assertTrue(self.member.check_password('fixture-temporary-Q5-only'))
        self.assertTrue(self.member.member_profile.must_change_password)

    def test_reset_invalidates_old_sessions_and_keys(self):
        old = Client();old.force_login(self.member)
        token = MemberToken.objects.create(user=self.member, label='old', digest='f' * 64, prefix='test')
        self.reset();token.refresh_from_db()
        self.assertIsNotNone(token.revoked_at)
        self.assertIn(reverse('login'), old.get(reverse('workspace_home'))['Location'])

    def test_https_reset_accepts_same_origin_with_real_csrf_validation(self):
        client=Client(enforce_csrf_checks=True);client.force_login(self.admin)
        url=reverse('member_reset_password',args=[self.member.pk])
        response=client.get(url,secure=True)
        self.assertEqual(response['Referrer-Policy'],'same-origin')
        token=re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"',response.content.decode()).group(1)
        with patch('core.member_management.secrets.token_urlsafe',return_value='fixture-temporary-Q5-only'):
            response=client.post(url,{'confirm':'reset','csrfmiddlewaretoken':token},secure=True,HTTP_ORIGIN='https://testserver',HTTP_REFERER='https://testserver'+url)
        self.assertContains(response,'临时密码已生成')
        self.assertIn('no-store',response['Cache-Control'])
        self.member.refresh_from_db();self.assertTrue(self.member.check_password('fixture-temporary-Q5-only'))

    def test_https_reset_rejects_null_foreign_and_missing_sources(self):
        client=Client(enforce_csrf_checks=True);client.force_login(self.admin)
        url=reverse('member_reset_password',args=[self.member.pk])
        response=client.get(url,secure=True)
        token=re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"',response.content.decode()).group(1)
        for headers in ({'HTTP_ORIGIN':'null'},{'HTTP_ORIGIN':'https://other.example'},{}):
            response=client.post(url,{'confirm':'reset','csrfmiddlewaretoken':token},secure=True,**headers)
            self.assertEqual(response.status_code,403)
        self.assertEqual(client.post(url,{'confirm':'reset'},secure=True,HTTP_ORIGIN='https://testserver').status_code,403)
        self.member.refresh_from_db();self.assertTrue(self.member.check_password('original-Q5-password'))

    def test_reset_inactive_account_does_not_reactivate_it(self):
        self.member.is_active = False;self.member.save(update_fields=['is_active'])
        self.reset();self.member.refresh_from_db();self.assertFalse(self.member.is_active)

    def test_reset_requires_confirmation_and_cannot_target_self(self):
        self.assertNotContains(self.client.post(reverse('member_reset_password', args=[self.member.pk]), {}), '临时密码已生成')
        self.assertEqual(self.client.post(reverse('member_reset_password', args=[self.admin.pk]), {'confirm':'reset'}).status_code,403)

    def test_temporary_login_is_gated_until_new_password_is_set(self):
        self.reset();self.client.logout()
        self.client.post(reverse('login'), {'username': self.member.username, 'password':'fixture-temporary-Q5-only'})
        for name in ('workspace_home', 'members', 'profile'):
            self.assertEqual(self.client.get(reverse(name))['Location'], reverse('required_password_change'))
        self.assertEqual(self.client.get(reverse('messages_unread'), HTTP_ACCEPT='application/json').status_code,403)
        data={'new_password1':'different-new-XY9-password','new_password2':'different-new-XY9-password'}
        self.assertEqual(self.client.post(reverse('required_password_change'),data)['Location'], reverse('workspace_home'))
        self.member.refresh_from_db();self.assertFalse(self.member.member_profile.must_change_password)
        self.assertIsNone(self.member.member_profile.temporary_password_expires_at)
        self.assertEqual(self.client.get(reverse('workspace_home')).status_code,200)

    def test_temporary_password_cannot_be_reused_as_new_password(self):
        self.reset();self.member.refresh_from_db();self.client.force_login(self.member)
        response=self.client.post(reverse('required_password_change'),{'new_password1':'fixture-temporary-Q5-only','new_password2':'fixture-temporary-Q5-only'})
        self.assertContains(response,'请设置与临时密码不同的新密码')
        self.member.refresh_from_db();self.assertTrue(self.member.member_profile.must_change_password)

    def test_password_save_preserves_concurrent_identity_change(self):
        from django.contrib.auth.forms import SetPasswordForm
        self.reset()
        User.objects.filter(pk=self.member.pk).update(is_staff=True)
        self.member.refresh_from_db();self.client.force_login(self.member)
        original = SetPasswordForm.is_valid
        def demote_during_validation(form):
            valid = original(form)
            User.objects.filter(pk=self.member.pk).update(is_staff=False, first_name='新名称')
            return valid
        with patch.object(SetPasswordForm,'is_valid',demote_during_validation):
            response=self.client.post(reverse('required_password_change'),{'new_password1':'different-new-XY9-password','new_password2':'different-new-XY9-password'})
        self.assertEqual(response.status_code,302)
        self.member.refresh_from_db()
        self.assertFalse(self.member.is_staff)
        self.assertEqual(self.member.first_name,'新名称')
        self.assertTrue(self.member.check_password('different-new-XY9-password'))

    def test_expired_temporary_password_cannot_login_or_continue_session(self):
        self.reset();MemberProfile.objects.filter(user=self.member).update(temporary_password_expires_at=timezone.now()-timezone.timedelta(seconds=1))
        self.assertFalse(RoleLoginForm(data={'username':self.member.username,'password':'fixture-temporary-Q5-only'}).is_valid())
        self.member.refresh_from_db();self.client.force_login(self.member)
        self.assertEqual(self.client.get(reverse('required_password_change'))['Location'],reverse('login'))

    def test_desktop_login_reports_mandatory_password_change(self):
        import json
        self.reset();self.client.logout()
        result=self.client.post(reverse('desktop_api',args=['login']),json.dumps({'username':self.member.username,'password':'fixture-temporary-Q5-only'}),content_type='application/json')
        self.assertTrue(result.json()['mustChangePassword'])
        self.assertTrue(self.client.get(reverse('desktop_api',args=['status'])).json()['mustChangePassword'])

    def test_delete_requires_exact_name_confirmation(self):
        response=self.client.post(reverse('member_delete',args=[self.member.pk]),{'confirm_username':'wrong'})
        self.assertContains(response,'请准确输入');self.member.refresh_from_db();self.assertTrue(self.member.is_active)

    def test_delete_requires_handoff_and_preserves_historical_objects(self):
        project=Project.objects.create(name='交接项目',owner=self.member,created_by=self.member)
        task=Task.objects.create(project=project,title='交接任务',assignee=self.member,created_by=self.member)
        competition=Competition.objects.create(name='交接比赛',owner=self.member,created_by=self.member)
        experiment=Experiment.objects.create(number='HANDOFF-1',title='保留实验',created_by=self.member,project=project)
        finance=FinanceEntry.objects.create(memo='保留账目',occurred_on=timezone.localdate(),kind='income',amount=5,created_by=self.member)
        message=ChatMessage.objects.create(room='private',author=self.member,recipient=self.next,body='保留消息')
        self.assertContains(self.delete(),'该成员仍有负责事项，请选择接任成员')
        self.member.refresh_from_db();self.assertTrue(self.member.is_active)
        self.assertEqual(self.delete(successor=str(self.next.pk)).status_code,302)
        for item,field in ((project,'owner_id'),(task,'assignee_id'),(competition,'owner_id')):
            item.refresh_from_db();self.assertEqual(getattr(item,field),self.next.pk)
        self.assertTrue(project.members.filter(pk=self.next.pk).exists())
        for item in (experiment,finance,message):self.assertTrue(type(item).objects.filter(pk=item.pk).exists())
        self.member.refresh_from_db();self.assertTrue(self.member.is_active);self.assertTrue(self.member.has_usable_password())
        membership=TeamMembership.objects.get(team_id=1,user=self.member)
        self.assertFalse(membership.active);self.assertIsNotNone(membership.deleted_at)
        self.assertFalse(MemberProfile.objects.filter(user=self.member,deleted_at__isnull=False).exists())
        self.assertNotIn(self.member.pk,[u.pk for u in self.client.get(reverse('members')).context['accounts']])

    def test_api_owner_handoff_requires_active_admin(self):
        PoolSettings.objects.create(pk=1,owner=self.member)
        self.assertContains(self.delete(successor=str(self.next.pk)),'交接给一位在用管理员')
        self.assertEqual(self.delete(successor=str(self.admin.pk)).status_code,302)
        self.assertEqual(PoolSettings.objects.get(pk=1).owner_id,self.admin.pk)

    def test_deleted_account_cannot_be_reactivated_and_credentials_revoked(self):
        invite,_=Invite.issue(self.member)
        token=MemberToken.objects.create(user=self.member,label='old',digest='b'*64,prefix='test')
        self.delete();invite.refresh_from_db();token.refresh_from_db()
        self.assertIsNotNone(invite.revoked_at);self.assertIsNotNone(token.revoked_at)
        self.assertEqual(self.client.post(reverse('members'),{'id':self.member.pk,'action':'activate'}).status_code,404)
        self.assertTrue(RoleLoginForm(data={'username':self.member.username,'password':'original-Q5-password'}).is_valid())

    def test_deleted_peer_history_remains_read_only(self):
        ChatMessage.objects.create(room='private',author=self.member,recipient=self.next,body='以前的聊天')
        self.delete();self.client.force_login(self.next)
        url=reverse('messages_private',args=[self.member.pk])
        self.assertContains(self.client.get(url),'以前的聊天')
        self.assertContains(self.client.get(url),'deleted-conversation')
        self.assertEqual(self.client.post(url,{'body':'新消息'},HTTP_ACCEPT='application/json').status_code,403)
        self.assertEqual(self.client.get(reverse('messages_private',args=[self.admin.pk])).status_code,200)

    def test_current_account_and_last_admin_are_protected(self):
        for name in ('member_delete','member_reset_password'):
            self.assertEqual(self.client.post(reverse(name,args=[self.admin.pk]),{'confirm_username':self.admin.username,'confirm':'reset'}).status_code,403)
        self.assertEqual(self.client.post(reverse('members'),{'id':self.admin.pk,'action':'demote'}).status_code,403)
        self.admin.refresh_from_db();self.assertTrue(self.admin.is_staff);self.assertTrue(self.admin.is_active)

    def test_capture_current_member_and_announcement_pages(self):
        folder=os.environ.get('WORKBENCH_CAPTURE_UI')
        if not folder:return
        path=Path(folder);path.mkdir(parents=True,exist_ok=True)
        project=Project.objects.create(name='资料库项目',owner=self.member,created_by=self.admin)
        Task.objects.create(project=project,title='接任任务',assignee=self.member,created_by=self.admin)
        for title in ('第一条独立公告','第二条独立公告'):Announcement.objects.create(title=title,body='公告正文')
        for file,name,args in [('member-directory.html','members',[]),('member-delete.html','member_delete',[self.member.pk]),('member-reset.html','member_reset_password',[self.member.pk]),('navigation-announcements.html','workspace_home',[])]:
            response=self.client.get(reverse(name,args=args));self.assertEqual(response.status_code,200);(path/file).write_bytes(response.content)
            if name=='member_reset_password':
                (path/'member-reset-policy.json').write_text(json.dumps({'referrer_policy':response['Referrer-Policy']}),encoding='utf-8')
        response=self.reset();(path/'member-temporary.html').write_bytes(response.content)
        self.member.refresh_from_db()
        self.client.force_login(self.member);response=self.client.get(reverse('required_password_change'))
        self.assertEqual(response.status_code,200)
        (path/'member-required-password.html').write_bytes(response.content)
