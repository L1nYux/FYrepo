from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('core', '0051_discovery_private_inbox'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.AddField(model_name='teamopening', name='paused', field=models.BooleanField(default=False)),
        migrations.CreateModel(name='AccountPreferences', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('sticker_order', models.JSONField(blank=True, default=list)),
            ('saved_files', models.JSONField(blank=True, default=list)),
            ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
        ]),
    ]
