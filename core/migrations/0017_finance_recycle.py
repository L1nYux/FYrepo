from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [('core', '0016_chat_unread_indexes')]
    operations = [
        migrations.AddField(model_name='financeentry', name='archived_at', field=models.DateTimeField('删除时间', blank=True, null=True)),
        migrations.AddField(model_name='expenseclaim', name='archived_at', field=models.DateTimeField('删除时间', blank=True, null=True)),
    ]
