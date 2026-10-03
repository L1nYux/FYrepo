from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0015_repair_legacy_schema')]
    operations = [
        migrations.AddIndex(model_name='chatmessage', index=models.Index(fields=['room','id'], name='chat_room_unread')),
        migrations.AddIndex(model_name='chatmessage', index=models.Index(fields=['recipient','room','id'], name='chat_peer_unread')),
    ]
