from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [('core','0027_application_release'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [migrations.CreateModel(name='PersonalThreadRead', fields=[
        ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
        ('channel',models.CharField(max_length=50)),
        ('last_message_id',models.PositiveBigIntegerField(default=0)),
        ('user',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,to=settings.AUTH_USER_MODEL)),
    ],options={'constraints':[models.UniqueConstraint(fields=('user','channel'),name='personal_thread_read_unique')]})]
