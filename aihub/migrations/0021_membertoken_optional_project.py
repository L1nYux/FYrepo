from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('aihub', '0020_personal_assistant_history')]
    operations = [
        migrations.AddField(model_name='membertoken', name='project', field=models.ForeignKey(
            blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
            related_name='member_api_keys', to='core.project')),
        migrations.AddField(model_name='membertoken', name='project_bound', field=models.BooleanField(default=False)),
    ]
