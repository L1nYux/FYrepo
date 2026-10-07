from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('aihub', '0004_assistant_conversations')]
    operations = [
        migrations.AddField(model_name='allowance', name='history_days', field=models.PositiveIntegerField(default=0, verbose_name='AI 对话保留天数（0 表示自行删除）')),
        migrations.CreateModel(name='ApiRateWindow', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('scope', models.CharField(max_length=80, unique=True)),
            ('minute', models.PositiveBigIntegerField(default=0)),
            ('requests', models.PositiveIntegerField(default=0)),
            ('leases', models.JSONField(default=dict)),
            ('expires_at', models.DateTimeField()),
        ]),
    ]
