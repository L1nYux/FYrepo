from django.db import migrations, models
import django.db.models.deletion
import re


def backfill(apps,schema_editor):
    alias=schema_editor.connection.alias
    Notice=apps.get_model('core','AccountNotice');Message=apps.get_model('core','PersonalMessage');Offer=apps.get_model('core','RecruitmentOffer')
    Preference=apps.get_model('core','ConversationPreference')
    User=apps.get_model('auth','User')
    active=set(User.objects.using(alias).filter(is_active=True).values_list('pk',flat=True))
    for notice in Notice.objects.using(alias).filter(read_at__isnull=True).select_related('application__opening__team').iterator():
        peer=None
        if notice.application_id:
            item=notice.application
            peer=(item.reviewed_by_id or item.opening.team.owner_id) if notice.user_id==item.applicant_id else item.applicant_id
        else:
            match=re.fullmatch(r'/discover/offers/([1-9][0-9]*)/',notice.target_url)
            offer=Offer.objects.using(alias).filter(pk=match[1]).first() if match else None
            if offer:peer=offer.issued_by_id if notice.user_id==offer.recipient_id else offer.recipient_id
        blocked=peer and (Preference.objects.using(alias).filter(user_id=notice.user_id,channel='person:'+str(peer),blocked=True).exists() or Preference.objects.using(alias).filter(user_id=peer,channel='person:'+str(notice.user_id),blocked=True).exists())
        if peer and peer!=notice.user_id and peer in active and notice.user_id in active and not blocked:
            row,_=Message.objects.using(alias).get_or_create(notice_id=notice.pk,defaults={'sender_id':peer,'recipient_id':notice.user_id,
                'body':(notice.title+'\n'+notice.body).strip()[:2000],'relation_verified':True,'contact_source':'discovery',
                'references':[{'kind':'discovery-notice','pk':notice.pk}],'created_at':notice.created_at})
            Message.objects.using(alias).filter(pk=row.pk).update(created_at=notice.created_at)


class Migration(migrations.Migration):
    dependencies=[('core','0050_closed_teams_announcement_archive')]
    operations=[migrations.AddField(model_name='personalmessage',name='contact_source',field=models.CharField(max_length=20,blank=True,editable=False)),
        migrations.AddField(model_name='personalmessage',name='notice',field=models.OneToOneField(null=True,blank=True,editable=False,on_delete=django.db.models.deletion.SET_NULL,related_name='private_message',to='core.accountnotice')),
        migrations.RunPython(backfill,migrations.RunPython.noop)]
