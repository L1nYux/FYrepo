from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies=[('aihub','0006_point_credits')]
    operations=[
        migrations.AddField(model_name='provider',name='quota_kind',field=models.CharField(max_length=12,default='auto',verbose_name='额度类型',choices=[('auto','自动识别'),('plan','订阅套餐'),('account','按量账户余额')])),
        migrations.AddField(model_name='provider',name='quota_snapshot',field=models.JSONField(default=dict,editable=False)),
    ]
