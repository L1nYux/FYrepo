import django.db.models
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0046_opening_planned_headcount')]
    operations = [migrations.CreateModel(
        name='LocalChatDelivery',
        fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('kind', models.CharField(choices=[('personal', '私聊'), ('group', '群聊')], max_length=8)),
            ('message_id', models.PositiveBigIntegerField()),
            ('group_id', models.PositiveBigIntegerField(blank=True, null=True)),
            ('recipients', models.JSONField(default=list)),
            ('received', models.JSONField(default=dict)),
            ('fully_received_at', models.DateTimeField(blank=True, db_index=True, null=True)),
            ('purged_at', models.DateTimeField(blank=True, null=True)),
            ('created_at', models.DateTimeField(auto_now_add=True)),
        ],
        options={'constraints': [models.UniqueConstraint(fields=('kind', 'message_id'), name='local_chat_delivery_unique')]},
    )]
