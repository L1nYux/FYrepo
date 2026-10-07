import io
import os
import tempfile
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from .avatars import AvatarForm, avatar_url
from .models import MemberProfile, PublicProfile, ChatMessage, ChatReadState, Attachment

def image_file(fmt='PNG', size=(800,400)):
    buffer=io.BytesIO();Image.new('RGB',size,(60,130,180)).save(buffer,fmt)
    return SimpleUploadedFile('photo.png',buffer.getvalue(),content_type='image/png')

class AvatarTests(TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.settings=override_settings(MEDIA_ROOT=self.temp.name);self.settings.enable();self.addCleanup(self.settings.disable)
        self.user=User.objects.create_user('avatar-user',password='test-password')
        self.client.force_login(self.user)

    def upload(self, file=None):
        return self.client.post(reverse('profile'),{'action':'avatar','avatar':file or image_file()})

    def test_upload_normalizes_and_does_not_change_identity(self):
        self.assertEqual(self.upload().status_code,302);self.user.refresh_from_db()
        profile=self.user.member_profile
        self.assertEqual(profile.tier,MemberProfile.DEVELOPER)
        self.assertFalse(self.user.is_staff)
        with profile.avatar.open('rb') as source:
            with Image.open(source) as image:
                self.assertEqual(image.format,'WEBP');self.assertEqual(image.size,(400,400));self.assertNotIn('exif',image.info)
        self.assertNotIn('photo',profile.avatar.name)

    def test_existing_normal_role_is_preserved(self):
        MemberProfile.objects.create(user=self.user,tier=MemberProfile.NORMAL)
        self.assertEqual(self.upload().status_code,302);self.user.refresh_from_db()
        self.assertEqual(self.user.member_profile.tier,MemberProfile.NORMAL)

    def test_oversized_and_disguised_files_are_rejected(self):
        for file in (SimpleUploadedFile('evil.jpg',b'<svg onload="bad()"/>'),SimpleUploadedFile('large.png',b'x'*(5*1024*1024+1))):
            self.assertEqual(self.upload(file).status_code,200)
        self.assertFalse(MemberProfile.objects.filter(user=self.user,avatar__gt='').exists())

    def test_non_supported_image_and_large_dimensions_are_rejected(self):
        form=AvatarForm(files={'avatar':image_file('BMP')});self.assertFalse(form.is_valid())
        with patch('core.avatars.MAX_PIXELS',100):
            self.assertFalse(AvatarForm(files={'avatar':image_file(size=(11,10))}).is_valid())

    def test_animated_image_rejected(self):
        buffer=io.BytesIO();Image.new('RGB',(8,8),'red').save(buffer,'WEBP',save_all=True,append_images=[Image.new('RGB',(8,8),'blue')],duration=100)
        self.assertFalse(AvatarForm(files={'avatar':SimpleUploadedFile('animated.webp',buffer.getvalue())}).is_valid())

    def test_replace_and_remove_delete_previous_file_after_commit(self):
        self.upload();self.user.refresh_from_db();old=self.user.member_profile.avatar.name
        with self.captureOnCommitCallbacks(execute=True): self.upload()
        self.assertFalse(Path(self.temp.name,old).exists());self.user.refresh_from_db();current=self.user.member_profile.avatar.name
        self.assertNotEqual(old,current)
        with self.captureOnCommitCallbacks(execute=True): self.client.post(reverse('profile'),{'action':'avatar_remove'})
        self.user.refresh_from_db();self.assertFalse(self.user.member_profile.avatar);self.assertFalse(Path(self.temp.name,current).exists())

    def test_private_access_public_opt_in_and_revocation(self):
        self.upload();self.user.refresh_from_db();url=avatar_url(self.user)
        response=self.client.get(url);self.assertEqual(response.status_code,200);self.assertEqual(response['Content-Type'],'image/webp');response.close()
        guest=Client();self.assertEqual(guest.get(url).status_code,404)
        public=PublicProfile.objects.create(user=self.user,is_public=True)
        response=guest.get(url);self.assertEqual(response.status_code,200);self.assertIn('no-store',response['Cache-Control']);response.close()
        public.is_public=False;public.save();self.assertEqual(guest.get(url).status_code,404)

    def test_old_url_invalid_after_replace_and_disabled_user_hidden(self):
        self.upload();self.user.refresh_from_db();old=avatar_url(self.user);self.upload()
        self.assertEqual(self.client.get(old).status_code,404)
        self.user.refresh_from_db();url=avatar_url(self.user);self.user.is_active=False;self.user.save()
        self.assertEqual(Client().get(url).status_code,404)

    def test_csrf_and_own_account_only(self):
        secure=Client(enforce_csrf_checks=True);secure.force_login(self.user)
        self.assertEqual(secure.post(reverse('profile'),{'action':'avatar','avatar':image_file()}).status_code,403)
        other=User.objects.create_user('other-avatar');self.upload();self.assertFalse(MemberProfile.objects.filter(user=other).exists())

    def test_profile_status_and_template_use_uploaded_avatar(self):
        self.upload();self.user.refresh_from_db();url=avatar_url(self.user)
        self.assertContains(self.client.get(reverse('profile')),url)
        self.assertEqual(self.client.get('/desktop/api/status/').json()['avatarUrl'],url)
        capture=os.environ.get('WORKBENCH_CAPTURE_UI')
        if capture:
            folder=Path(capture);folder.mkdir(parents=True,exist_ok=True)
            (folder/'avatar-profile.html').write_bytes(self.client.get(reverse('profile')).content)
            (folder/'avatar.webp').write_bytes(self.user.member_profile.avatar.read())
            self.user.member_profile.avatar.close()

class ConversationTests(TestCase):
    def setUp(self):
        self.me=User.objects.create_user('chat-me');self.peer=User.objects.create_user('chat-peer');self.third=User.objects.create_user('chat-third',is_staff=True)
        self.client.force_login(self.me);self.other=Client();self.other.force_login(self.peer)
        self.old=ChatMessage.objects.create(room='private',author=self.peer,recipient=self.me,body='needle old')
        self.group=ChatMessage.objects.create(room='developers',author=self.peer,body='needle group')
        from .models import Team, TeamMembership
        Team.objects.filter(pk=1).update(owner=self.third)
        TeamMembership.objects.filter(team_id=1,user=self.third).update(role='owner')
        self.key=f'dm:{self.peer.pk}'

    def manage(self,action,key=None,confirm='yes'):
        return self.client.post(reverse('messages_manage'),{'channel':key or self.key,'action':action,'confirm':confirm})

    def history(self,**params):
        return self.client.get(reverse('messages_history'),{'channel':self.key,**params})

    def test_mute_sync_and_unmute_preserves_unread(self):
        data=self.manage('mute').json();self.assertEqual(data['total'],1);self.assertEqual(data['channels']['person:'+str(self.peer.pk)],1)
        self.assertIn('person:'+str(self.peer.pk),self.client.get(reverse('messages_unread')).json()['muted_channels'])
        self.assertEqual(self.manage('unmute').json()['total'],2)
        self.assertFalse(ChatReadState.objects.filter(user=self.peer,muted=True).exists())

    def test_muting_group_excludes_all_total_badges(self):
        self.manage('mute','developers')
        self.assertEqual(self.client.get(reverse('messages_unread')).json()['total'],1)
        self.assertEqual(self.client.get('/workspace/').context['unread_total'],1)

    def test_clear_only_own_history_search_poll_and_ai(self):
        from aihub.agent import available
        self.manage('clear')
        self.assertEqual(self.history().json()['messages'],[])
        self.assertEqual(self.client.get(reverse('messages_private_poll',args=[self.peer.pk]),{'known':str(self.old.pk)}).json()['removed'],[self.old.pk])
        self.assertFalse(available(self.me,'message').filter(pk=self.old.pk).exists())
        self.assertTrue(available(self.peer,'message').filter(pk=self.old.pk).exists())
        self.assertEqual(len(self.other.get(reverse('messages_history'),{'channel':f'dm:{self.me.pk}'}).json()['messages']),1)
        self.assertTrue(ChatMessage.objects.filter(pk=self.old.pk).exists())

    def test_clear_future_messages_appear_and_cannot_reedit_cleared(self):
        own=ChatMessage.objects.create(room='private',author=self.me,recipient=self.peer,body='withdrawn',withdrawn_at=__import__('django.utils.timezone',fromlist=['now']).now())
        self.manage('clear');new=ChatMessage.objects.create(room='private',author=self.peer,recipient=self.me,body='new')
        self.assertEqual([m['id'] for m in self.history().json()['messages']],[new.pk])
        self.assertEqual(self.client.post(reverse('message_action',args=[own.pk]),{'action':'draft'}).status_code,404)

    def test_clear_and_remove_need_confirmation_and_post(self):
        for action in ('clear','remove'):
            self.assertEqual(self.manage(action,confirm='').status_code,400)
        self.assertEqual(self.client.get(reverse('messages_manage')).status_code,405)
        self.assertEqual(self.manage('bad').status_code,400)

    def test_remove_keeps_history_and_restores_on_new_message(self):
        self.assertIn(self.key,self.manage('remove').json()['hidden_channels'])
        self.assertEqual(len(self.history().json()['messages']),1)
        ChatMessage.objects.create(room='private',author=self.peer,recipient=self.me,body='after remove')
        self.assertNotIn(self.key,self.client.get(reverse('messages_unread')).json()['hidden_channels'])

    def test_explicit_open_restores_removed_conversation(self):
        self.manage('remove');self.client.get(reverse('messages_private',args=[self.peer.pk]))
        self.assertFalse(ChatReadState.objects.get(user=self.me,channel=self.key).removed)

    def test_third_party_cannot_search_manage_or_jump_into_private_chat(self):
        client=Client();client.force_login(self.third)
        self.assertEqual(client.get(reverse('messages_history'),{'channel':self.key,'around':self.old.pk}).status_code,404)
        data=client.get(reverse('messages_history'),{'channel':self.key}).json()
        self.assertEqual(data['messages'],[])
        self.assertEqual(self.history(around=self.group.pk).status_code,404)

    def test_invalid_filters_and_channel_are_rejected(self):
        for args in ({'start':'wrong'},{'start':'2026-10-05','end':'2026-10-01'},{'around':'9223372036854775808'},{'kind':'bad'}):
            self.assertEqual(self.history(**args).status_code,400)
        self.assertEqual(self.client.get(reverse('messages_history'),{'channel':'private'}).status_code,403)

    def test_search_keyword_author_and_no_cross_conversation_results(self):
        self.assertEqual([m['id'] for m in self.history(q='needle').json()['messages']],[self.old.pk])
        self.assertEqual(self.history(author=self.me.pk).json()['messages'],[])
        self.old.hidden_by.add(self.me);self.assertEqual(self.history(q='needle').json()['messages'],[])

    def test_file_image_and_reference_filters(self):
        from .models import ChatReference, Announcement
        image=Attachment.objects.create(chat_message=self.old,file='test/picture.png',original_name='IMAGE.PNG',uploaded_by=self.peer)
        Attachment.objects.create(chat_message=self.old,file='test/report.txt',original_name='report.txt',uploaded_by=self.peer)
        announcement=Announcement.objects.create(title='reference',body='data')
        ChatReference.objects.create(message=self.old,kind='announcement',announcement=announcement)
        for kind in ('image','file','reference'):
            self.assertEqual([m['id'] for m in self.history(kind=kind).json()['messages']],[self.old.pk])
        self.assertEqual([m['id'] for m in self.history(q='report').json()['messages']],[self.old.pk])

    def test_search_pagination_and_context_for_old_message(self):
        ChatMessage.objects.bulk_create([ChatMessage(room='private',author=self.peer,recipient=self.me,body='needle '+str(i)) for i in range(220)])
        first=self.history(q='needle').json();self.assertEqual(len(first['messages']),50)
        second=self.history(q='needle',before=first['next_before']).json()
        self.assertTrue(set(m['id'] for m in first['messages']).isdisjoint(m['id'] for m in second['messages']))
        around=self.history(around=self.old.pk).json();self.assertEqual(around['target'],self.old.pk)
        self.assertEqual(around['messages'][0]['id'],self.old.pk);self.assertGreater(around['cursor'],around['messages'][-1]['id'])

    def test_csrf_and_guest_access(self):
        secure=Client(enforce_csrf_checks=True);secure.force_login(self.me)
        self.assertEqual(secure.post(reverse('messages_manage'),{'action':'clear','channel':self.key,'confirm':'yes'}).status_code,403)
        self.assertEqual(Client().get(reverse('messages_history'),{'channel':self.key}).status_code,302)

    def test_capture_messages_for_ui(self):
        response=self.client.get(reverse('messages_private',args=[self.peer.pk]));self.assertEqual(response.status_code,200)
        self.assertContains(response,'data-history-dialog');self.assertContains(response,'data-message-actions')
        capture=os.environ.get('WORKBENCH_CAPTURE_UI')
        if capture: Path(capture,'conversations.html').write_bytes(self.client.get(reverse('messages_hub')).content)
