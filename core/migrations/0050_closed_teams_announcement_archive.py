from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def convert(apps, schema_editor):
    alias=schema_editor.connection.alias
    Workspace=apps.get_model('core','Workspace');Team=apps.get_model('core','Team');Membership=apps.get_model('core','TeamMembership')
    Pool=apps.get_model('aihub','PoolSettings')
    for space in Workspace.objects.using(alias).filter(kind='personal',owner__isnull=False).iterator():
        user=space.owner
        team=Team.objects.using(alias).create(solo_owner_id=user.pk,owner_id=user.pk,
            name=(user.first_name or user.username)[:90]+'的团队',member_limit=1,listed=False,recruitment_mode='closed',active=space.active and user.is_active)
        Membership.objects.using(alias).create(team_id=team.pk,user_id=user.pk,role='owner',active=space.active and user.is_active)
        Workspace.objects.using(alias).filter(pk=space.pk).update(kind='team',team_id=team.pk)
        for model in apps.get_models():
            names={f.name for f in model._meta.fields}
            if {'workspace','team'}<=names:
                model._base_manager.using(alias).filter(workspace_id=space.pk,team_id__isnull=True).update(team_id=team.pk)
        Pool.objects.using(alias).get_or_create(workspace_id=space.pk,defaults={'team_id':team.pk,'owner_id':user.pk})


class Migration(migrations.Migration):
    dependencies=[('core','0049_chat_images'),('aihub','0022_poolmodel_output_default')]
    operations=[
        migrations.AddField(model_name='team',name='solo_owner',field=models.OneToOneField(blank=True,null=True,editable=False,on_delete=django.db.models.deletion.PROTECT,related_name='closed_team',to=settings.AUTH_USER_MODEL)),
        migrations.RemoveConstraint(model_name='workspace',name='workspace_exact_owner'),
        migrations.AddConstraint(model_name='workspace',constraint=models.CheckConstraint(condition=models.Q(kind='personal',owner__isnull=False,team__isnull=True)|models.Q(kind='team',team__isnull=False),name='workspace_exact_owner')),
        migrations.AddField(model_name='announcement',name='deleted_at',field=models.DateTimeField(null=True,blank=True,editable=False)),
        migrations.RunPython(convert),
    ]
