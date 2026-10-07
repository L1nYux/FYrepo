from django.db import migrations
from django.utils import timezone


def complete(apps,schema_editor):
    db=schema_editor.connection.alias
    Application=apps.get_model('core','TeamApplication')
    Member=apps.get_model('core','TeamMembership')
    Invite=apps.get_model('core','Invite')
    Notice=apps.get_model('core','AccountNotice')
    for application in Application.objects.using(db).filter(state='accepted').select_related('opening__team','applicant').order_by('created_at','pk').iterator():
        team=application.opening.team
        old=Member.objects.using(db).filter(team_id=team.pk,user_id=application.applicant_id).first()
        existing=old and old.active and old.deleted_at is None and old.role in ('owner','admin','member')
        reviewer=Member.objects.using(db).filter(team_id=team.pk,user_id=application.reviewed_by_id,active=True,deleted_at__isnull=True).first()
        authorized=reviewer and (reviewer.role in ('owner','admin') or reviewer.role=='member' and 'recruitment' in reviewer.permissions)
        seats=Member.objects.using(db).filter(team_id=team.pk,active=True,deleted_at__isnull=True,role__in=['owner','admin','member']).count()
        eligible=team.active and application.applicant.is_active and authorized and not (old and not old.active and old.deleted_at is None) and seats<team.member_limit
        if existing or eligible:
            if not existing:Member.objects.using(db).update_or_create(team_id=team.pk,user_id=application.applicant_id,defaults={'role':'member','active':True,'deleted_at':None,'permissions':[]})
            Application.objects.using(db).filter(pk=application.pk).update(state='joined')
            Notice.objects.using(db).create(user_id=application.applicant_id,application_id=application.pk,title=team.name+' 的入队申请已完成',body='原申请已经通过，你已加入团队。',target_url='/messages/teams/?team='+str(team.pk))
        else:
            Application.objects.using(db).filter(pk=application.pk).update(state='pending')
            if application.reviewed_by_id:Notice.objects.using(db).create(user_id=application.reviewed_by_id,application_id=application.pk,title='入队申请需要重新核对',body='原申请因团队容量或资格变化未能完成入队，请核对后审核。',target_url='/messages/teams/review/?team='+str(team.pk))
        if application.invite_id:Invite.objects.using(db).filter(pk=application.invite_id,used_at__isnull=True).update(revoked_at=timezone.now())


class Migration(migrations.Migration):
    dependencies=[('core','0041_funding_settlement')]
    operations=[migrations.RunPython(complete)]
