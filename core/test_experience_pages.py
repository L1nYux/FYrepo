import io
from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from . import test_community
from .models import ConversationPreference, PersonalMessage, MessageUpload, ChatGroup, GroupMember, GroupMessage
from .chat_media import preview


class ExperiencePageChecks(TestCase):
    setUp = test_community.CommunityTests.setUp

    def image(self):
        data=io.BytesIO();Image.new('RGB',(24,16),'green').save(data,'PNG')
        return SimpleUploadedFile('image.png',data.getvalue(),content_type='image/png')

    def test_authorized_independent_pages_and_profile(self):
        for view in ['chat','edit','settings','background','history']:
            response=self.client.get('/app/pages/',{'view':view,'channel':'person:'+str(self.worker.pk)})
            self.assertEqual(response.status_code,200,view)
            self.assertContains(response,'data-experience-page="'+view+'"')
            self.assertTrue(response.context['is_messages'])
            self.assertEqual(response.context['shell_section'], '消息')
            import os
            from pathlib import Path
            folder=os.environ.get('WORKBENCH_CAPTURE_UI')
            if folder:Path(folder,'experience-'+view+'.html').write_bytes(response.content)
        profile=self.client.get('/app/pages/',{'view':'profile','member':self.worker.pk})
        self.assertEqual(profile.status_code,200)
        import os
        from pathlib import Path
        folder=os.environ.get('WORKBENCH_CAPTURE_UI')
        if folder:Path(folder,'experience-profile.html').write_bytes(profile.content)
        self.client.force_login(self.outside)
        self.assertEqual(self.client.get('/app/pages/',{'view':'chat','channel':'person:'+str(self.worker.pk)}).status_code,403)

    def test_background_is_private_and_validated(self):
        key='person:'+str(self.worker.pk)
        response=self.client.post('/app/preferences/',{'channel':key,'action':'background','image':self.image()})
        self.assertEqual(response.status_code,200)
        url=response.json()['background_url'];self.assertEqual(self.client.get(url).status_code,200)
        self.client.force_login(self.worker)
        self.assertEqual(self.client.get(url).status_code,403)
        self.client.force_login(self.owner)
        bad=self.client.post('/app/preferences/',{'channel':key,'action':'background','image':SimpleUploadedFile('fake.png',b'not an image')})
        self.assertEqual(bad.status_code,400)
        self.client.post('/app/preferences/',{'channel':key,'action':'background_clear'})
        self.assertEqual(self.client.get(url).status_code,404)

    def test_group_mosaic_and_manager_avatar(self):
        group=ChatGroup.objects.create(owner=self.owner,name='好友群')
        GroupMember.objects.create(group=group,user=self.owner,admin=True)
        GroupMember.objects.create(group=group,user=self.worker)
        avatar='/app/groups/'+str(group.pk)+'/avatar/'
        self.assertEqual(self.client.get(avatar).status_code,200)
        self.assertEqual(self.client.get('/app/pages/',{'view':'group','channel':'group:'+str(group.pk)}).status_code,200)
        upload='/app/groups/'+str(group.pk)+'/image/'
        self.assertEqual(self.client.post(upload,{'image':self.image()}).status_code,200)
        self.client.force_login(self.worker)
        self.assertEqual(self.client.post(upload,{'image':self.image()}).status_code,403)
        self.client.force_login(self.outside)
        self.assertEqual(self.client.get(avatar).status_code,403)

    def test_mark_read_advances_cursor_and_keeps_new_messages_unread(self):
        key='person:'+str(self.worker.pk)
        PersonalMessage.objects.create(sender=self.worker,recipient=self.owner,body='first')
        self.assertEqual(self.client.post('/app/preferences/',{'channel':key,'action':'read'}).status_code,200)
        from .communication import unread
        self.assertEqual(unread(self.owner).get(key,0),0)
        PersonalMessage.objects.create(sender=self.worker,recipient=self.owner,body='second')
        self.assertEqual(unread(self.owner)[key],1)

    def test_attachment_preview_and_new_row_identity(self):
        message=PersonalMessage.objects.create(sender=self.worker,recipient=self.owner,body='')
        MessageUpload.objects.create(personal=message,original_name='photo.png',file='test/image.png')
        self.assertEqual(preview(message),'【图片】')
        data=self.client.get('/app/notifications/').json()
        row=next(r for r in data['conversations'] if r['key']=='person:'+str(self.worker.pk))
        self.assertEqual(row['preview'],'【图片】');self.assertEqual(row['member_id'],self.worker.pk)

    def test_all_group_mode_uses_latest_regular_message(self):
        group=ChatGroup.objects.create(owner=self.owner,name='群')
        GroupMember.objects.create(group=group,user=self.owner,admin=True)
        GroupMember.objects.create(group=group,user=self.worker)
        GroupMember.objects.create(group=group,user=self.outside,admin=True)
        GroupMessage.objects.create(group=group,author=self.outside,body='notice')
        newest=GroupMessage.objects.create(group=group,author=self.worker,body='regular')
        ConversationPreference.objects.create(user=self.owner,channel='group:'+str(group.pk),notification_mode='all')
        row=next(r for r in self.client.get('/app/notifications/').json()['conversations'] if r['key']=='group:'+str(group.pk))
        self.assertEqual(row['message_id'],newest.pk)
        self.assertIn('regular',row['preview'])

    def test_legacy_group_settings_keep_new_preferences_in_sync(self):
        group=ChatGroup.objects.create(owner=self.owner,name='群设置')
        member=GroupMember.objects.create(group=group,user=self.owner,admin=True,pinned=True,muted=True)
        key='group:'+str(group.pk)
        data=self.client.post('/app/preferences/',{'channel':key,'action':'clear_manual'}).json()
        self.assertTrue(data['pinned'])
        self.assertEqual(data['notification_mode'],'none')
        response=self.client.post('/messages/groups/'+str(group.pk)+'/manage/',{'action':'settings','setting':'pinned'})
        self.assertEqual(response.status_code,302)
        pref=ConversationPreference.objects.get(user=self.owner,channel=key)
        self.assertFalse(pref.pinned)
        self.client.post('/messages/groups/'+str(group.pk)+'/settings/',{'action':'unmute'})
        pref.refresh_from_db();self.assertEqual(pref.notification_mode,'all')
        self.client.post('/app/preferences/',{'channel':key,'action':'notifications','mode':'important'})
        member.refresh_from_db();self.assertFalse(member.muted)
        self.client.post('/app/preferences/',{'channel':key,'action':'notifications','mode':'none'})
        member.refresh_from_db();self.assertTrue(member.muted)

    def test_legacy_team_mute_is_reflected_on_settings_page(self):
        from .communication import default_group
        group=default_group(self.team)
        key='team:'+str(self.team.pk)
        response=self.client.post('/messages/manage/',{'channel':'developers','action':'mute'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.client.get('/app/preferences/',{'channel':key}).json()['notification_mode'],'none')
        self.client.post('/app/preferences/',{'channel':key,'action':'notifications','mode':'important'})
        self.assertFalse(GroupMember.objects.get(group=group,user=self.owner).muted)
