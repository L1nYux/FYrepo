import core.tenancy
import django.db.models.deletion
import django.db.models.manager
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('aihub', '0025_agent_delegation')]
    operations = [
        migrations.AddField(model_name='assistantjob', name='execution', field=models.JSONField(default=dict, editable=False)),
        migrations.AddField(model_name='assistantjob', name='event_sequence', field=models.PositiveBigIntegerField(default=0, editable=False)),
        migrations.AddField(model_name='assistantjob', name='lease_token', field=models.UUIDField(null=True, editable=False)),
        migrations.AddField(model_name='assistantjob', name='lease_expires_at', field=models.DateTimeField(null=True, editable=False)),
        migrations.AddIndex(model_name='assistantjob', index=models.Index(fields=['state','lease_expires_at','created_at'],name='assistant_job_queue')),
        migrations.CreateModel(
            name='AssistantEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('sequence', models.PositiveBigIntegerField()),
                ('kind', models.CharField(max_length=40)),
                ('payload', models.JSONField(default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('job', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='events', to='aihub.assistantjob')),
                ('team', models.ForeignKey(blank=True, default=core.tenancy.team_id, editable=False, null=True, on_delete=django.db.models.deletion.PROTECT, to='core.team')),
                ('workspace', models.ForeignKey(default=core.tenancy.required_workspace_id, editable=False, on_delete=django.db.models.deletion.PROTECT, to='core.workspace')),
            ],
            options={'ordering':['sequence'], 'default_manager_name':'objects', 'base_manager_name':'all_objects'},
            managers=[('objects',django.db.models.manager.Manager()),('all_objects',django.db.models.manager.Manager())],
        ),
        migrations.AddConstraint(model_name='assistantevent', constraint=models.UniqueConstraint(fields=('job','sequence'), name='assistant_event_sequence')),
    ]
