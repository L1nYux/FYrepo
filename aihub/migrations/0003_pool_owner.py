import os
from django.conf import settings
from django.db import migrations,models
import django.db.models.deletion


def choose_owner(apps,schema_editor):
    User=apps.get_model(*settings.AUTH_USER_MODEL.split('.'))
    PoolSettings=apps.get_model('aihub','PoolSettings')
    db=schema_editor.connection.alias
    users=User.objects.using(db).filter(is_active=True,is_staff=True)
    username=os.environ.get('WORKBENCH_API_OWNER_USERNAME','').strip()
    owner=users.filter(username=username).first() if username else users.first() if users.count()==1 else None
    if owner:
        PoolSettings.objects.using(db).get_or_create(pk=1)
        PoolSettings.objects.using(db).filter(pk=1,owner__isnull=True).update(owner=owner)


class Migration(migrations.Migration):
    dependencies=[('aihub','0002_weekly_allowances'),migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations=[migrations.AddField(model_name='poolsettings',name='owner',field=models.ForeignKey(
        null=True,blank=True,on_delete=django.db.models.deletion.PROTECT,related_name='owned_api_pools',to=settings.AUTH_USER_MODEL)),
        migrations.RunPython(choose_owner,migrations.RunPython.noop)]
