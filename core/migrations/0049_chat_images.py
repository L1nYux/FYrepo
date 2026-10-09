from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0048_conversation_preferences_scan_login')]
    operations = [
        migrations.AddField(model_name='chatgroup', name='avatar', field=models.FileField(blank=True, upload_to='chat-groups')),
        migrations.AddField(model_name='conversationpreference', name='background', field=models.FileField(blank=True, upload_to='chat-backgrounds')),
    ]
