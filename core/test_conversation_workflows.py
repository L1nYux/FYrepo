"""Regression checks for the file/sticker/recruitment workflows in 0.6.1."""
import io
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from PIL import Image
from . import test_community
from .models import (TeamOpening, TeamApplication, PersonalMessage, MessageUpload,
                     Friendship, ConversationPreference, Sticker)
from .tenancy import scope
from .recruitment import listings, sync_recruitment


class ConversationWorkflowTests(TestCase):
    setUp = test_community.CommunityTests.setUp

    def opening(self, **values):
        opening = TeamOpening.objects.create(team=self.team,title='有名额的职位',
            description='岗位说明',planned_headcount=values.pop('planned_headcount',2),**values)
        sync_recruitment(self.team.pk)
        return opening

    def friend(self):
        pair=sorted([self.owner.pk,self.outside.pk])
        Friendship.objects.create(first_id=pair[0],second_id=pair[1])

    def files(self):
        row=PersonalMessage.objects.create(sender=self.owner,recipient=self.worker,
            body='原消息说明',relation_verified=True)
        first=MessageUpload.objects.create(personal=row,original_name='第一份.txt',file=SimpleUploadedFile('first.txt',b'first'))
        second=MessageUpload.objects.create(personal=row,original_name='第二份.txt',file=SimpleUploadedFile('second.txt',b'second'))
        return row,first,second

    def test_stop_withdraws_square_and_keeps_application_history(self):
        item=self.opening()
        application=TeamApplication.objects.create(opening=item,applicant=self.outside,resume='申请资料')
        self.assertTrue(listings().filter(pk=self.team.pk).exists())
        self.client.post(reverse('recruitment_manage'),{'action':'stop_recruitment'})
        self.team.refresh_from_db();item.refresh_from_db()
        self.assertFalse(self.team.listed);self.assertEqual(self.team.recruitment_mode,'closed')
        self.assertFalse(item.active);self.assertFalse(listings().filter(pk=self.team.pk).exists())
        self.assertTrue(TeamApplication.objects.filter(pk=application.pk).exists())

    def test_last_pause_withdraws_and_resume_republishes(self):
        item=self.opening()
        self.client.post(reverse('recruitment_manage'),{'action':'pause','opening':item.pk})
        self.assertFalse(listings().filter(pk=self.team.pk).exists())
        self.client.post(reverse('recruitment_manage'),{'action':'resume','opening':item.pk})
        self.assertTrue(listings().filter(pk=self.team.pk).exists())

    def test_old_full_listing_is_hidden_without_migration(self):
        item=self.opening(planned_headcount=1)
        TeamApplication.objects.create(opening=item,applicant=self.outside,resume='已加入',state='joined')
        self.assertFalse(listings().filter(pk=self.team.pk).exists())
        from .discovery_messages import available
        self.assertFalse(available(self.outside,self.owner))

    def test_square_count_excludes_full_and_paused_openings(self):
        self.opening()
        full=self.opening(planned_headcount=1)
        TeamApplication.objects.create(opening=full,applicant=self.outside,resume='已加入',state='joined')
        self.opening(active=False,paused=True)
        result=self.client.get(reverse('team_square'))
        self.assertEqual(result.status_code,200)
        team=list(result.context['listing_teams'])[0]
        self.assertEqual(team.opening_count,1)
        detail=self.client.get(reverse('team_listing',args=[team.pk]))
        self.assertEqual(len(detail.context['openings']),1)

    def test_missing_legacy_capacity_does_not_advertise_recruitment(self):
        item=self.opening(planned_headcount=None)
        self.assertFalse(listings().filter(pk=self.team.pk).exists())
        self.client.force_login(self.outside)
        self.assertEqual(self.client.post(reverse('team_apply',args=[item.pk]),{'resume':'直接投递'}).status_code,404)

    def test_team_capacity_hides_available_jobs_and_rejects_direct_application(self):
        from .models import Team
        item=self.opening()
        Team.objects.filter(pk=self.team.pk).update(member_limit=2)
        self.assertFalse(listings().filter(pk=self.team.pk).exists())
        self.client.force_login(self.outside)
        self.assertEqual(self.client.get(reverse('team_apply',args=[item.pk])).status_code,404)
        self.assertEqual(self.client.post(reverse('team_apply',args=[item.pk]),{'resume':'已经没有团队名额'}).status_code,404)
        self.assertFalse(TeamApplication.objects.filter(opening=item).exists())
        Team.objects.filter(pk=self.team.pk).update(member_limit=3)
        self.assertTrue(listings().filter(pk=self.team.pk).exists())

    def test_old_full_job_cannot_accept_application_by_direct_url(self):
        item=self.opening(planned_headcount=1)
        TeamApplication.objects.create(opening=item,applicant=self.worker,resume='已入队',state='joined')
        self.client.force_login(self.outside)
        self.assertEqual(self.client.post(reverse('team_apply',args=[item.pk]),{'resume':'直接投递'}).status_code,404)
        self.assertFalse(TeamApplication.objects.filter(opening=item,applicant=self.outside).exists())

    def test_non_hr_member_cannot_stop_team_recruitment(self):
        self.opening();self.client.force_login(self.worker)
        self.assertEqual(self.client.post(reverse('recruitment_manage'),{'action':'stop_recruitment'}).status_code,403)
        self.assertTrue(listings().filter(pk=self.team.pk).exists())

    def test_recipients_include_contacts_without_previous_messages_and_exclude_blocks(self):
        self.friend()
        data=self.client.get('/app/forward/').json()
        keys={item['key'] for item in data['contacts']}
        self.assertIn('person:'+str(self.worker.pk),keys)
        self.assertIn('person:'+str(self.outside.pk),keys)
        ConversationPreference.objects.create(user=self.worker,channel='person:'+str(self.owner.pk),blocked=True)
        data=self.client.get('/app/forward/').json()
        self.assertNotIn('person:'+str(self.worker.pk),{item['key'] for item in data['all']})

    def test_current_file_forward_has_one_attachment_and_repeat_has_no_duplicate_note(self):
        self.friend();row,first,second=self.files()
        payload={'source':'person:'+str(self.worker.pk),'id':row.pk,'target':'person:'+str(self.outside.pk),
                 'token':'conversation-forward-061-token','confirm':'yes','attachment':'upload:'+str(first.pk),'note':'请查看这份文件'}
        first_response=self.client.post('/app/forward/',payload)
        self.assertEqual(first_response.status_code,200,first_response.content)
        repeated=self.client.post('/app/forward/',payload)
        self.assertTrue(repeated.json()['repeated'])
        copies=PersonalMessage.objects.filter(sender=self.owner,recipient=self.outside)
        self.assertEqual(copies.count(),2)
        self.assertEqual(list(MessageUpload.objects.filter(personal__in=copies).values_list('original_name',flat=True)),[first.original_name])
        self.assertEqual(copies.filter(body='请查看这份文件').count(),1)
        self.assertFalse(copies.filter(body='原消息说明').exists())
        payload['attachment']='upload:'+str(second.pk)
        self.assertEqual(self.client.post('/app/forward/',payload).status_code,409)

    def test_file_forward_rejects_attachment_from_another_message(self):
        self.friend();row,first,_=self.files()
        unrelated=PersonalMessage.objects.create(sender=self.owner,recipient=self.worker,body='其他资料',relation_verified=True)
        file=MessageUpload.objects.create(personal=unrelated,original_name='其他.txt',file=SimpleUploadedFile('other.txt',b'other'))
        result=self.client.post('/app/forward/',{'source':'person:'+str(self.worker.pk),'id':row.pk,
            'target':'person:'+str(self.outside.pk),'token':'conversation-forward-other-token',
            'confirm':'yes','attachment':'upload:'+str(file.pk)})
        self.assertEqual(result.status_code,404)
        self.assertFalse(PersonalMessage.objects.filter(sender=self.owner,recipient=self.outside).exists())

    def test_lost_response_retry_confirms_existing_receipt_after_original_withdrawal(self):
        from django.utils import timezone
        self.friend();row,first,_=self.files()
        payload={'source':'person:'+str(self.worker.pk),'id':row.pk,'target':'person:'+str(self.outside.pk),
                 'token':'conversation-lost-response-token','confirm':'yes','attachment':'upload:'+str(first.pk),'note':'断线后的留言'}
        self.assertEqual(self.client.post('/app/forward/',payload).status_code,200)
        PersonalMessage.objects.filter(pk=row.pk).update(withdrawn_at=timezone.now())
        result=self.client.post('/app/forward/',payload)
        self.assertEqual(result.status_code,200,result.content)
        self.assertTrue(result.json()['repeated'])
        self.assertEqual(PersonalMessage.objects.filter(sender=self.owner,recipient=self.outside).count(),2)
        payload['note']='不同的留言'
        self.assertEqual(self.client.post('/app/forward/',payload).status_code,409)

    def test_withdrawn_original_rejects_a_new_forward(self):
        from django.utils import timezone
        self.friend();row,first,_=self.files()
        PersonalMessage.objects.filter(pk=row.pk).update(withdrawn_at=timezone.now())
        result=self.client.post('/app/forward/',{'source':'person:'+str(self.worker.pk),'id':row.pk,
            'target':'person:'+str(self.outside.pk),'token':'conversation-withdrawn-new-token',
            'confirm':'yes','attachment':'upload:'+str(first.pk)})
        self.assertEqual(result.status_code,400)
        self.assertFalse(PersonalMessage.objects.filter(sender=self.owner,recipient=self.outside).exists())

    def test_sticker_only_request_produces_a_single_message(self):
        image=io.BytesIO();Image.new('RGB',(12,12),'blue').save(image,'PNG')
        with scope(self.team):
            sticker=Sticker.objects.create(created_by=self.owner,name='单张表情',mime='image/png',
                file=SimpleUploadedFile('sticker.png',image.getvalue()))
        sticker.favorites.add(self.owner)
        result=self.client.post(reverse('personal_chat',args=[self.worker.pk]),
            {'body':'','references':'[]','sticker_id':sticker.pk},HTTP_ACCEPT='application/json')
        self.assertEqual(result.status_code,200,result.content)
        message=PersonalMessage.objects.get(sender=self.owner,recipient=self.worker)
        self.assertEqual(message.sticker_id,sticker.pk);self.assertEqual(message.body,'')
        self.assertEqual(message.references,[]);self.assertFalse(message.uploads.exists())
