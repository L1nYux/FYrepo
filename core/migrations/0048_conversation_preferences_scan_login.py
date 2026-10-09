import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('core','0047_local_chat_delivery'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(name='MessageForwardReceipt',fields=[
            ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
            ('token',models.CharField(max_length=64)),('source',models.CharField(max_length=80)),
            ('target',models.CharField(max_length=50)),('created_at',models.DateTimeField(auto_now_add=True)),
            ('user',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,to=settings.AUTH_USER_MODEL)),
        ],options={'constraints':[models.UniqueConstraint(fields=['user','token'],name='message_forward_receipt_unique')]}),
        migrations.CreateModel(name='ConversationPreference', fields=[
            ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
            ('channel',models.CharField(max_length=50)), ('remark',models.CharField(max_length=80,blank=True)),
            ('note',models.CharField(max_length=1000,blank=True)), ('pinned',models.BooleanField(default=False)),
            ('phone',models.CharField(max_length=100,blank=True)), ('tags',models.CharField(max_length=200,blank=True)),
            ('manual_unread',models.BooleanField(default=False)), ('blocked',models.BooleanField(default=False)),
            ('notification_mode',models.CharField(max_length=12,default='important',choices=[('all','全部'),('important','仅重要'),('none','完全免打扰')])),
            ('user',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,to=settings.AUTH_USER_MODEL)),
        ], options={'constraints':[models.UniqueConstraint(fields=['user','channel'],name='conversation_preference_unique')]}),
        migrations.CreateModel(name='ScanLoginChallenge',fields=[
            ('id',models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False,serialize=False)),
            ('token_hash',models.CharField(max_length=64)),('session_hash',models.CharField(max_length=64)),
            ('device',models.CharField(max_length=100)),('expires_at',models.DateTimeField()),
            ('confirmed_at',models.DateTimeField(null=True)),('consumed_at',models.DateTimeField(null=True)),
            ('user',models.ForeignKey(null=True,on_delete=django.db.models.deletion.CASCADE,to=settings.AUTH_USER_MODEL)),
        ]),
    ]
