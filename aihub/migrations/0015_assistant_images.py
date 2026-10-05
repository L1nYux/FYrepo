import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies=[('aihub','0014_budgetweek_base_limit_recorded_and_more'),migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations=[
        migrations.AddField(model_name='poolmodel',name='supports_images',field=models.BooleanField(blank=True,default=None,null=True,verbose_name='支持图片输入（留空自动识别）')),
        migrations.CreateModel(name='AssistantImage',fields=[
            ('id',models.UUIDField(default=uuid.uuid4,editable=False,primary_key=True,serialize=False)),
            ('data',models.TextField(editable=False)),('width',models.PositiveIntegerField()),('height',models.PositiveIntegerField()),
            ('created_at',models.DateTimeField(auto_now_add=True,db_index=True)),
            ('user',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,to=settings.AUTH_USER_MODEL)),
        ]),
        migrations.AddField(model_name='assistantjob',name='images',field=models.ManyToManyField(blank=True,related_name='jobs',to='aihub.assistantimage')),
    ]
