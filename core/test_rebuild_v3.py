"""0.3 boundaries exercised through real session, navigation and message endpoints."""
import io
import json
import re
import tempfile
import zipfile
import os
from pathlib import Path
from unittest.mock import patch
from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User, Permission
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from .models import (Workspace, MemberProfile, TeamMembership, Friendship, PersonalMessage,
    MessageUpload, RegistrationChallenge, ChatMessage, Task, Project, WorkspaceEvent)
from .tenancy import scope
from .admission import create_team


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',WORKBENCH_OPEN_REGISTRATION=True)
class RebuildV3Tests(TestCase):
    def setUp(self):
        with scope(None,http=True):
            self.me=User.objects.create_user('v3-me','me@example.com','password-Q93-only')
            self.friend=User.objects.create_user('v3-peer','peer@example.com','password-Q93-only')
            self.stranger=User.objects.create_user('v3-other')
            self.root=User.objects.create_superuser('v3-root')
            for user in (self.me,self.friend,self.stranger,self.root):MemberProfile.objects.create(user=user)
        self.space=Workspace.objects.create(kind='personal',owner=self.me)
        Friendship.objects.create(first=self.me,second=self.friend)
        self.client.force_login(self.me)
        session=self.client.session;session['workbench-space']='personal';session.save()
        self.thread=reverse('personal_chat',args=[self.friend.pk])
        self.settings=reverse('personal_thread_settings',args=[self.friend.pk])

    def send(self,text='hello',**fields):
        result=self.client.post(self.thread,{'body':text,**fields},HTTP_ACCEPT='application/json')
        self.assertEqual(result.status_code,200,result.content[:300])
        return PersonalMessage.objects.filter(sender=self.me).latest('pk')

    def test_delegated_software_identity_has_visible_independent_account_management(self):
        self.me.user_permissions.add(Permission.objects.get(codename='manage_platform_accounts'))
        self.assertContains(self.client.get(reverse('profile')),'软件管理')
        self.assertRedirects(self.client.get(reverse('platform')),reverse('platform_accounts'))
        self.assertTrue(self.client.get(reverse('desktop_api',args=['status'])).json()['isPlatformAdmin'])
        self.assertEqual(self.client.post(reverse('platform'),{'action':'capacity','team':'1','member_limit':'100'}).status_code,403)

    def test_delegated_project_controls_match_their_authorized_endpoints(self):
        team=create_team(self.root,'delegated company')
        TeamMembership.objects.create(team=team,user=self.me,permissions=['projects'])
        with scope(team):project=Project.objects.create(name='delegated project',owner=self.root,created_by=self.root)
        self.client.post(reverse('team_switch'),{'team':team.pk})
        self.assertContains(self.client.get(reverse('dashboard')),reverse('project_new'))
        self.assertContains(self.client.get(reverse('project_detail',args=[project.pk])),reverse('project_edit',args=[project.pk]))
        self.assertEqual(self.client.post(reverse('project_close',args=[project.pk])).status_code,302)
        project=Project.all_objects.get(pk=project.pk);self.assertEqual(project.status,Project.CLOSED)

    def test_capture_personal_and_friend_group_interfaces(self):
        folder=os.environ.get('WORKBENCH_CAPTURE_UI')
        if not folder:return
        from .models import ChatGroup, GroupMember, GroupMessage
        group=ChatGroup.objects.create(name='独立好友群',owner=self.me)
        GroupMember.objects.create(group=group,user=self.me,admin=True)
        GroupMember.objects.create(group=group,user=self.friend)
        GroupMessage.objects.create(group=group,author=self.friend,body='好友群里的消息')
        self.send('个人空间里的消息')
        directory=Path(folder);directory.mkdir(parents=True,exist_ok=True)
        for name,url in [('v3-personal.html',self.thread),('v3-friend-group.html',reverse('group_chat',args=[group.pk]))]:
            response=self.client.get(url);self.assertEqual(response.status_code,200)
            (directory/name).write_bytes(response.content)

    def test_imported_older_message_keeps_time_order_without_stale_unread(self):
        recent=self.send('recent personal')
        old=PersonalMessage.objects.create(sender=self.friend,recipient=self.me,body='older imported',relation_verified=True)
        PersonalMessage.objects.filter(pk=old.pk).update(created_at=timezone.now()-timedelta(days=2))
        inbox=self.client.get(reverse('messages_social'))
        self.assertContains(inbox,'recent personal');self.assertNotContains(inbox,'older imported')
        thread=self.client.get(self.thread).content.decode()
        self.assertLess(thread.index('older imported'),thread.rindex('recent personal'))
        self.assertEqual(self.client.get(reverse('messages_unread')).json()['total'],0)
        history=self.client.get(reverse('personal_thread_history',args=[self.friend.pk])).json()['messages']
        self.assertEqual([row['id'] for row in history],[recent.pk,old.pk])
        earlier=self.client.get(reverse('personal_thread_history',args=[self.friend.pk]),{'before':recent.pk}).json()['messages']
        self.assertEqual([row['id'] for row in earlier],[old.pk])

    def test_personal_mute_clear_remove_and_new_message_restore(self):
        message=self.send('clear me')
        self.client.post(self.settings,{'action':'mute'})
        reply=PersonalMessage.objects.create(sender=self.friend,recipient=self.me,body='new',relation_verified=True)
        unread=self.client.get(reverse('messages_unread')).json()
        key='person:'+str(self.friend.pk)
        self.assertIn(key,unread['muted_channels']);self.assertEqual(unread['total'],0)
        self.client.post(self.settings,{'action':'clear','confirm':'yes'})
        self.assertEqual(self.client.get(reverse('personal_thread_history',args=[self.friend.pk])).json()['messages'],[])
        self.client.post(self.settings,{'action':'remove','confirm':'yes'})
        self.assertNotContains(self.client.get(reverse('messages_social')),'data-conversation-key="'+key+'"')
        PersonalMessage.objects.create(sender=self.friend,recipient=self.me,body='after removal',relation_verified=True)
        self.assertContains(self.client.get(reverse('messages_social')),'data-conversation-key="'+key+'"')

    def test_personal_poll_reports_removed_messages(self):
        message=self.send()
        self.client.post(reverse('personal_message_action',args=[self.friend.pk,message.pk]),{'action':'delete'})
        data=self.client.get(self.thread,{'known':str(message.pk),'after':message.pk},HTTP_ACCEPT='application/json').json()
        self.assertEqual(data['removed'],[message.pk])
        self.assertEqual(self.client.post(reverse('personal_message_action',args=[self.friend.pk,message.pk]),{'action':'draft'}).status_code,404)

    def test_withdraw_reedit_retains_file_and_preview_hides_text(self):
        with tempfile.TemporaryDirectory() as folder, override_settings(MEDIA_ROOT=folder):
            message=self.send('secret draft',attachments=SimpleUploadedFile('note.txt',b'hello'))
            action=reverse('personal_message_action',args=[self.friend.pk,message.pk])
            self.client.post(action,{'action':'withdraw'})
            self.assertNotContains(self.client.get(reverse('messages_social')),'secret draft')
            draft=self.client.post(action,{'action':'draft'}).json()['draft']
            self.assertEqual(draft['attachments'],['note.txt'])
            resent=self.send('edited',resend_message=message.pk)
            upload=resent.uploads.get()
            self.assertEqual(upload.file.read(),b'hello');upload.file.close()
            self.assertEqual(self.client.get(reverse('personal_message_file',args=[message.uploads.get().pk])).status_code,403)

    def test_cleared_personal_files_cannot_be_downloaded(self):
        with tempfile.TemporaryDirectory() as folder, override_settings(MEDIA_ROOT=folder):
            message=self.send(attachments=SimpleUploadedFile('note.txt',b'hello'))
            url=reverse('personal_message_file',args=[message.uploads.get().pk])
            response=self.client.get(url);self.assertEqual(response.status_code,200);response.close()
            self.client.post(self.settings,{'action':'clear','confirm':'yes'})
            self.assertEqual(self.client.get(url).status_code,403)
            other=Client();other.force_login(self.friend)
            response=other.get(url);self.assertEqual(response.status_code,200);response.close()

    def test_no_relation_cannot_forge_history_or_steal_actions(self):
        message=PersonalMessage.objects.create(sender=self.me,recipient=self.stranger,body='forged')
        self.assertEqual(self.client.get(reverse('personal_chat',args=[self.stranger.pk])).status_code,404)
        self.assertEqual(self.client.post(reverse('personal_message_action',args=[self.stranger.pk,message.pk]),{'action':'delete'}).status_code,404)

    def test_default_group_poll_and_send_do_not_switch_personal_workspace(self):
        from .communication import default_group
        team=create_team(self.me,'company');TeamMembership.objects.create(team=team,user=self.friend)
        group=default_group(team)
        with scope(team):ChatMessage.objects.create(author=self.friend,room='developers',body='team-only')
        page=self.client.get(reverse('group_chat',args=[group.pk]))
        self.assertContains(page,'team-only');self.assertContains(page,'data-workspace="'+str(team.workspace.pk)+'"')
        self.assertEqual(self.client.session['workbench-space'],'personal')
        poll=self.client.get(reverse('messages_poll'),{'space':team.workspace.pk}).json()
        self.assertEqual(poll['messages'][0]['body'],'team-only')
        self.client.post(reverse('messages_hub')+'?space='+str(team.workspace.pk),{'body':'team response','references':'[]'},HTTP_ACCEPT='application/json')
        self.assertTrue(ChatMessage.all_objects.filter(workspace=team.workspace,body='team response').exists())
        self.assertEqual(self.client.get(reverse('desktop_api',args=['status'])).json()['spaceKind'],'personal')
        foreign=Client();foreign.force_login(self.stranger)
        self.assertEqual(foreign.get(reverse('messages_poll'),{'space':team.workspace.pk}).status_code,403)

    def test_reference_checks_original_space_and_finance_permissions(self):
        team=create_team(self.me,'company');TeamMembership.objects.create(team=team,user=self.friend)
        with scope(team):
            project=Project.objects.create(owner=self.me,created_by=self.me,name='scoped project')
            task=Task.objects.create(project=project,created_by=self.me,assignee=self.me,due_date=timezone.localdate(),title='shared task',description='task content')
        with scope(team):
            from .chat_references import card
            url=card('task',task)['url']
        other=Client();other.force_login(self.friend)
        self.assertContains(other.get(url),'task content')
        foreign=Client();foreign.force_login(self.stranger)
        self.assertEqual(foreign.get(url).status_code,403)

    def test_group_and_team_management_keep_messages_navigation(self):
        create_team(self.me,'company')
        page=self.client.get(reverse('messages_teams'))
        self.assertTrue(page.context['is_messages'])
        members=self.client.get(reverse('messages_team_members'))
        self.assertTrue(members.context['is_messages'])
        rename=self.client.post(reverse('messages_team_rename'),{'name':'renamed'})
        self.assertEqual(rename['Location'],reverse('messages_teams'))
        self.assertEqual(self.client.session['workbench-space'],'personal')

    def test_disband_is_distinct_from_platform_suspension(self):
        team=create_team(self.me,'company')
        self.client.post(reverse('team_switch'),{'team':team.pk})
        result=self.client.post(reverse('team_disband'),{'confirm':team.name})
        self.assertEqual(result.status_code,302);team.refresh_from_db();self.assertIsNotNone(team.disbanded_at)
        self.client.force_login(self.root)
        self.assertEqual(self.client.post(reverse('platform'),{'action':'enable','team':team.pk}).status_code,403)

    def test_team_owner_cannot_reset_a_personal_password(self):
        create_team(self.me,'company')
        self.assertEqual(self.client.get(reverse('member_reset_password',args=[self.friend.pk])).status_code,403)
        self.assertEqual(self.client.post(reverse('platform_accounts'),{'action':'grant_developer','user':self.me.pk,'reason':'self'}).status_code,403)

    def test_self_close_revokes_keys_stops_jobs_and_keeps_team_data(self):
        from aihub.models import Provider, AssistantJob
        from aihub.service import secret_path, store_key
        with tempfile.TemporaryDirectory() as folder, override_settings(DATA_DIR=folder):
            with scope(self.space):
                provider=Provider.objects.create(name='private',base_url='https://example.com')
                store_key(provider,'fake-private-key');job=AssistantJob.objects.create(user=self.me)
            with self.captureOnCommitCallbacks(execute=True):
                response=self.client.post(reverse('account_close'),{'password':'password-Q93-only','confirm':'注销'})
            self.assertEqual(response.status_code,302)
            self.assertNotIn(str(provider.pk),json.loads(secret_path().read_text()))
            self.assertTrue(AssistantJob.all_objects.get(pk=job.pk).cancel_requested)
            self.assertEqual(self.client.get(reverse('workspace_home')).status_code,302)

    def test_export_contains_personal_messages_without_other_users_data(self):
        self.send('export mine')
        PersonalMessage.objects.create(sender=self.friend,recipient=self.stranger,body='not mine',relation_verified=True)
        data=self.client.get(reverse('account_export')).content
        with zipfile.ZipFile(io.BytesIO(data)) as archive:content=archive.read('个人数据.json').decode()
        self.assertIn('export mine',content);self.assertNotIn('not mine',content)

    def test_workspace_writes_have_actor_and_authority(self):
        self.client.post(reverse('project_new'),{'name':'audit project','goal':'research','owner':self.me.pk,'members':[self.me.pk]})
        event=WorkspaceEvent.objects.filter(workspace=self.space,object_type='core.project',action='create').first()
        self.assertIsNotNone(event);self.assertEqual(event.actor_id,self.me.pk);self.assertEqual(event.authority['role'],'personal_owner')

    def challenge(self):
        from .registration_email import send_code
        from django.test import RequestFactory
        request=RequestFactory().post('/register/');request.session={}
        with patch('core.registration_email.send_mail',return_value=1) as send:
            send_code(request,'new-v3@example.com')
        return request,re.search(r'\d{6}',send.call_args.args[1]).group()

    def test_mail_code_is_database_backed_session_bound_and_single_use(self):
        from .registration_email import verify
        request,code=self.challenge()
        self.assertEqual(RegistrationChallenge.objects.count(),1)
        stolen=type('Request',(),{'session':{}})()
        with self.assertRaises(ValidationError):verify(stolen,'new-v3@example.com',code)
        verify(request,'new-v3@example.com',code)
        with self.assertRaises(ValidationError):verify(request,'new-v3@example.com',code)

    def test_mail_code_attempt_limit_and_expiry(self):
        from .registration_email import verify
        request,code=self.challenge()
        wrong='000000' if code!='000000' else '111111'
        for _ in range(5):
            with self.assertRaises(ValidationError):verify(request,'new-v3@example.com',wrong)
        with self.assertRaises(ValidationError):verify(request,'new-v3@example.com',code)
        self.assertEqual(RegistrationChallenge.objects.get().attempts,5)
        RegistrationChallenge.objects.update(attempts=0,expires_at=timezone.now()-timedelta(seconds=1))
        with self.assertRaises(ValidationError):verify(request,'new-v3@example.com',code)

    def test_mail_send_rate_limit_and_unconfigured_backend(self):
        from .registration_email import send_code
        request,_=self.challenge()
        with self.assertRaises(ValidationError):send_code(request,'new-v3@example.com')
        with override_settings(DEBUG=False,EMAIL_BACKEND='django.core.mail.backends.console.EmailBackend'):
            with self.assertRaises(ValidationError):send_code(request,'another@example.com')
