from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0012_merge_desktop_and_main'),
                    migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.AddField(model_name='chatmessage', name='withdrawn_at',
                            field=models.DateTimeField('撤回时间', null=True, blank=True)),
        migrations.AddField(model_name='chatmessage', name='hidden_by',
                            field=models.ManyToManyField(blank=True, related_name='hidden_chat_messages',
                                                         to=settings.AUTH_USER_MODEL)),
    ]
