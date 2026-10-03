from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0007_chat_content_references'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.AlterField(model_name='project', name='goal', field=models.TextField('项目目标', max_length=3000, blank=True)),
        migrations.AlterField(model_name='task', name='description', field=models.TextField('任务说明', max_length=5000, blank=True)),
        migrations.AddField(model_name='experiment', name='content', field=models.TextField('记录内容', max_length=30000, blank=True)),
        migrations.CreateModel(name='UserPresence', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('last_seen', models.DateTimeField(default=django.utils.timezone.now)),
            ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='presence', to=settings.AUTH_USER_MODEL)),
        ]),
    ]
