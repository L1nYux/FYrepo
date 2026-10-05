from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0022_announcement_release_data_and_more')]
    operations = [
        migrations.AddField('memberprofile', 'deleted_at', models.DateTimeField('账号删除时间', null=True, blank=True)),
        migrations.AddField('memberprofile', 'must_change_password', models.BooleanField('下次登录必须改密', default=False)),
        migrations.AddField('memberprofile', 'temporary_password_expires_at', models.DateTimeField('临时密码有效期', null=True, blank=True)),
    ]
