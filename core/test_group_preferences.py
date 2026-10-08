"""Group preferences persist per member and change the real chat surfaces."""
import os
from pathlib import Path
from django.contrib.auth.models import User
from django.test import TestCase, Client
from django.urls import reverse
from .admission import create_team
from .communication import default_group
from .models import GroupMember, ChatGroup, GroupMessage, ChatMessage, TeamMembership, MemberProfile, PersonalThreadRead, ChatReadState
from .tenancy import scope


class GroupPreferenceTests(TestCase):
    def setUp(self):
        with scope(None, http=True):
            self.owner=User.objects.create_user('group-owner')
            self.member=User.objects.create_user('group-member')
            self.outsider=User.objects.create_user('group-outsider')
            for user in (self.owner,self.member,self.outsider):MemberProfile.objects.create(user=user)
        self.team=create_team(self.owner,'群设置团队')
        TeamMembership.objects.create(team=self.team,user=self.member)
        self.default=default_group(self.team)
        self.group=ChatGroup.objects.create(owner=self.owner,name='协作群')
        for user in (self.owner,self.member):GroupMember.objects.create(group=self.group,user=user)
        self.client.force_login(self.member)
        session=self.client.session;session['workbench-space']='personal';session.save()

    def save(self,group,**fields):
        return self.client.post(reverse('group_manage',args=[group.pk])+'?space='+str(self.team.workspace.pk),
            {'action':'settings',**fields},HTTP_ACCEPT='application/json')

    def capture(self,name,response):
        folder=os.environ.get('WORKBENCH_CAPTURE_UI')
        if folder:
            path=Path(folder);path.mkdir(parents=True,exist_ok=True);(path/name).write_bytes(response.content)

    def test_all_preferences_persist_and_are_private_in_both_group_types(self):
        for group in (self.group,self.default):
            with self.subTest(default=group.is_default):
                response=self.save(group,nickname='  实验昵称  ',remark='我的备注',muted='on',pinned='on',show_nicknames='on')
                self.assertEqual(response.status_code,200)
                self.assertEqual(response.json()['preferences'],dict(nickname='实验昵称',remark='我的备注',muted=True,pinned=True,show_nicknames=True))
                self.assertEqual(response.json()['member'],{'id':self.member.pk,'display_name':'实验昵称'})
                own=GroupMember.objects.get(group=group,user=self.member)
                self.assertTrue(own.muted and own.pinned and own.show_nicknames)
                other=GroupMember.objects.get(group=group,user=self.owner)
                self.assertEqual(other.nickname,'');self.assertFalse(other.muted or other.pinned)
                if group.is_default:
                    self.assertTrue(ChatReadState.all_objects.get(workspace=self.team.workspace,user=self.member,channel='developers').muted)
                else:self.assertTrue(PersonalThreadRead.objects.get(user=self.member,channel='group:'+str(group.pk)).muted)
                for setting in ('muted','pinned','show_nicknames'):
                    self.assertEqual(self.save(group,setting=setting).status_code,200)
                own.refresh_from_db();self.assertFalse(own.muted or own.pinned or own.show_nicknames)
                self.assertEqual(own.nickname,'实验昵称')
                page=self.client.get(reverse('group_chat',args=[group.pk]))
                self.assertContains(page,'hide-group-nicknames')
                self.assertContains(page,'实验昵称')

    def test_nickname_render_poll_history_and_pin_order(self):
        GroupMessage.objects.create(group=self.group,author=self.member,body='昵称验证消息')
        GroupMessage.objects.create(group=self.group,author=self.owner,body='另一成员消息')
        with scope(self.team.workspace):ChatMessage.objects.create(author=self.member,room='developers',body='团队昵称验证消息')
        for group in (self.group,self.default):
            self.capture('preferences-'+('team' if group.is_default else 'group')+'.html',self.client.get(reverse('group_chat',args=[group.pk])))
            self.save(group,nickname='保存后的群昵称',pinned='on')
            page=self.client.get(reverse('group_chat',args=[group.pk]))
            self.assertContains(page,'<strong>保存后的群昵称</strong>',html=True)
            entries=page.context['communication_recent']
            self.assertTrue(entries[0]['pinned'])
            if group.is_default:
                data=self.client.get(reverse('messages_poll'),{'space':self.team.workspace.pk}).json()
            else:
                data=self.client.get(reverse('group_chat',args=[group.pk]),HTTP_ACCEPT='application/json').json()
                history=self.client.get(reverse('group_thread_history',args=[group.pk])).json()
                self.assertIn('保存后的群昵称',[row['author'] for row in history['messages']])
            self.assertIn('保存后的群昵称',[row['author'] for row in data['messages']])

    def test_outsider_cannot_change_preferences(self):
        self.client.force_login(self.outsider)
        for group in (self.group,self.default):self.assertIn(self.save(group,muted='on').status_code,(403,404))
        self.assertFalse(GroupMember.objects.filter(user=self.member,muted=True).exists())

    def test_muted_group_is_excluded_from_notification_total(self):
        from .messages import unread_payload
        key='group:'+str(self.group.pk)
        self.assertEqual(unread_payload(self.member,{key:3})['total'],3)
        self.save(self.group,muted='on')
        self.assertEqual(unread_payload(self.member,{key:3})['total'],0)
        self.save(self.group,setting='muted')
        self.assertEqual(unread_payload(self.member,{key:3})['total'],3)
