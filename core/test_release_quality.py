import io
import os
import tempfile
from pathlib import Path
from PIL import Image
from django.contrib.auth.models import User
from django.contrib.auth.hashers import make_password
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone
from . import operations
from .models import Experiment, ExperimentRun, ChatMessage, EmailVerificationCode, Sticker, PublicProfile


class ReleaseQualityTests(TestCase):
    def setUp(self):
        self.me=User.objects.create_user('quality-me');self.peer=User.objects.create_user('quality-peer');self.other=User.objects.create_user('quality-other')
        self.client.force_login(self.me)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        config=override_settings(MEDIA_ROOT=self.temp.name);config.enable();self.addCleanup(config.disable)

    def test_timestamp_ties_choose_newest_code(self):
        now=timezone.now();codes=[EmailVerificationCode.objects.create(user=self.me,email='m@example.com',code_hash=make_password('123456'),expires_at=now+timezone.timedelta(minutes=10)) for _ in range(2)]
        EmailVerificationCode.objects.filter(pk__in=[c.pk for c in codes]).update(created_at=now)
        self.assertEqual(EmailVerificationCode.latest_usable(self.me).pk,codes[-1].pk)
        self.assertEqual(list(EmailVerificationCode.objects.values_list('pk',flat=True)),[codes[1].pk,codes[0].pk])

    def test_empty_result_experiment_can_be_created_and_updated(self):
        response=self.client.post(reverse('experiment_new'),{'title':'准备做的新实验'})
        self.assertEqual(response.status_code,302)
        experiment=Experiment.objects.get();self.assertEqual(experiment.result,'');self.assertEqual(experiment.status,'design')
        response=self.client.get(reverse('experiment_new'));self.assertContains(response,'name="purpose"');self.assertNotContains(response,'type="hidden" name="purpose"')
        self.assertEqual(self.client.post(reverse('experiment_edit',args=[experiment.pk]),{'title':experiment.title,'status':'running','procedure':'方法'}).status_code,302)
        experiment.refresh_from_db();self.assertEqual(experiment.status,'running')

    def test_experiment_run_before_results_and_later_update(self):
        experiment=Experiment.objects.create(number='QUALITY-1',title='实验',created_by=self.me)
        self.assertEqual(self.client.post(reverse('experiment_run_new',args=[experiment.pk]),{'title':'第一批','status':'running','parameters':'temperature=0.2'}).status_code,302)
        run=ExperimentRun.objects.get();self.assertEqual(run.result,'')
        self.assertEqual(self.client.post(reverse('experiment_run_edit',args=[experiment.pk,run.pk]),{'title':'第一批','status':'completed','result':'输出数据'}).status_code,302)
        run.refresh_from_db();self.assertEqual(run.result,'输出数据');self.assertEqual(ExperimentRun.objects.count(),1)
        response=self.client.get(reverse('experiment_detail',args=[experiment.pk])+'?tab=runs');self.assertContains(response,'输出数据');self.capture('experiment-workspace.html',response)

    def test_run_cannot_be_added_to_other_members_unlinked_experiment(self):
        experiment=Experiment.objects.create(number='QUALITY-2',title='私有',created_by=self.other)
        self.assertEqual(self.client.post(reverse('experiment_run_new',args=[experiment.pk]),{'title':'冒用','status':'running'}).status_code,404)

    def test_lists_paginate_without_losing_equal_timestamp_rows(self):
        rows=Experiment.objects.bulk_create([Experiment(number='PAGE-'+str(i),title='实验 '+str(i),created_by=self.me) for i in range(35)])
        Experiment.objects.update(created_at=timezone.now())
        first=self.client.get(reverse('experiments'));second=self.client.get(reverse('experiments')+'?page=2')
        self.assertEqual(len(first.context['entries']),30);self.assertEqual(len(second.context['entries']),5)
        self.assertFalse({r.pk for r in first.context['entries']} & {r.pk for r in second.context['entries']})

    def test_quote_requires_same_visible_conversation(self):
        original=ChatMessage.objects.create(author=self.peer,recipient=self.me,room='private',body='被引用消息')
        response=self.client.post(reverse('messages_private',args=[self.peer.pk]),{'body':'回复','quoted_message':original.pk},HTTP_ACCEPT='application/json')
        self.assertEqual(response.status_code,201);self.assertEqual(response.json()['message']['quote']['text'],'被引用消息')
        self.assertEqual(self.client.post(reverse('messages_hub'),{'body':'泄漏','quoted_message':original.pk},HTTP_ACCEPT='application/json').status_code,404)
        original.withdrawn_at=timezone.now();original.save()
        from .messages import serialize
        self.assertEqual(serialize(ChatMessage.objects.get(pk=response.json()['message']['id']),self.me)['quote']['text'],'原消息已撤回或不可用')

    def test_notice_cannot_be_withdrawn(self):
        message=ChatMessage.objects.create(author=self.me,room='developers',kind='notice',body='领取提示')
        self.assertEqual(self.client.post(reverse('message_action',args=[message.pk]),{'action':'withdraw'}).status_code,403)

    def test_member_card_only_returns_shared_public_profile(self):
        self.peer.email='private@example.com';self.peer.save();PublicProfile.objects.create(user=self.peer,bio='未公开资料')
        response=self.client.get(reverse('member_card',args=[self.peer.pk]));self.assertEqual(response.status_code,200)
        self.assertNotContains(response,'private@example.com');self.assertNotContains(response,'未公开资料')
        PublicProfile.objects.filter(user=self.peer).update(is_public=True,bio='公开介绍')
        self.assertEqual(self.client.get(reverse('member_card',args=[self.peer.pk])).json()['bio'],'公开介绍')

    def image(self,animated=False):
        buffer=io.BytesIO();first=Image.new('RGB',(40,40),'red')
        if animated:first.save(buffer,format='GIF',save_all=True,append_images=[Image.new('RGB',(40,40),'blue')],duration=100,loop=0)
        else:first.save(buffer,format='PNG')
        return SimpleUploadedFile('emoji.gif' if animated else 'emoji.png',buffer.getvalue())

    def test_verified_sticker_upload_send_and_favorite_removal(self):
        upload=self.client.post(reverse('stickers'),{'file':self.image()});self.assertEqual(upload.status_code,201)
        sticker=Sticker.objects.get();response=self.client.post(reverse('messages_private',args=[self.peer.pk]),{'sticker_id':sticker.pk},HTTP_ACCEPT='application/json')
        self.assertEqual(response.status_code,201);self.assertEqual(response.json()['message']['sticker']['id'],sticker.pk)
        self.client.force_login(self.other);self.assertEqual(self.client.get(reverse('sticker_file',args=[sticker.pk])).status_code,404)
        self.client.force_login(self.peer);response=self.client.get(reverse('sticker_file',args=[sticker.pk]));self.assertEqual(response.status_code,200);response.close()
        self.assertEqual(self.client.post(reverse('stickers'),{'action':'favorite','id':sticker.pk}).status_code,200)
        self.assertEqual(self.client.post(reverse('stickers'),{'action':'remove','id':sticker.pk}).status_code,200)
        self.assertEqual(self.peer.favorite_stickers.count(),0)

    def test_gif_is_still_animated(self):
        response=self.client.post(reverse('stickers'),{'file':self.image(True)});self.assertEqual(response.status_code,201)
        sticker=Sticker.objects.get()
        with sticker.file.open('rb') as file:
            with Image.open(file) as image:self.assertEqual(image.n_frames,2)

    def test_sticker_rejects_disguised_html(self):
        response=self.client.post(reverse('stickers'),{'file':SimpleUploadedFile('bad.gif',b'<script>alert(1)</script>')})
        self.assertEqual(response.status_code,400);self.assertFalse(Sticker.objects.exists())

    def test_error_pages_are_independent_of_database(self):
        request=RequestFactory().get('/missing')
        with self.assertNumQueries(0):
            self.assertEqual(operations.not_found(request,Exception()).status_code,404)
            self.assertEqual(operations.server_error(request).status_code,500)

    def test_healthz_returns_no_internal_configuration(self):
        response=self.client.get('/healthz/');self.assertEqual(response.json(),{'status':'ok'})

    def capture(self,name,response):
        if os.environ.get('WORKBENCH_CAPTURE_UI'):
            folder=Path(os.environ['WORKBENCH_CAPTURE_UI']);folder.mkdir(parents=True,exist_ok=True);(folder/name).write_bytes(response.content)
