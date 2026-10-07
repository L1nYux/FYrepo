from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies=[('aihub','0007_provider_quota')]
    operations=[migrations.AddField(model_name='assistantjob',name='retry_of',field=models.ForeignKey(null=True,blank=True,on_delete=django.db.models.deletion.SET_NULL,to='aihub.assistantjob',related_name='retries'))]
