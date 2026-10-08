from django.db import migrations, models
import django.db.models.deletion
import core.tenancy


def assign_legacy_runs(apps, schema_editor):
    """The user confirmed all existing samples belong to the sole team."""
    alias = schema_editor.connection.alias
    Run = apps.get_model('sampling', 'SamplingRun')
    pending = Run.objects.using(alias).filter(workspace__isnull=True)
    if not pending.exists():
        return
    Team = apps.get_model('core', 'Team')
    teams = list(Team.objects.using(alias).filter(active=True).values_list('pk', flat=True)[:2])
    if len(teams) != 1:
        raise RuntimeError('旧样本归属迁移需要现有唯一团队；检测到多个团队或没有团队，请先指定归属。')
    Workspace = apps.get_model('core', 'Workspace')
    space, _ = Workspace.objects.using(alias).get_or_create(team_id=teams[0], defaults={'kind': 'team'})
    if pending.filter(project__isnull=False).exclude(project__workspace_id=space.pk).exists():
        raise RuntimeError('旧样本关联项目与唯一团队归属不一致，请先核对，未迁移数据。')
    pending.update(workspace_id=space.pk)


class Migration(migrations.Migration):
    dependencies = [('sampling', '0003_candidatepaper_cross_disciplinary_journal'),
                    ('core', '0044_documentaccess_project_required')]
    operations = [
        migrations.AddField(model_name='samplingrun', name='workspace',
            field=models.ForeignKey(null=True, editable=False, on_delete=django.db.models.deletion.PROTECT,
                                    to='core.workspace', verbose_name='归属')),
        migrations.RunPython(assign_legacy_runs, migrations.RunPython.noop),
        migrations.AlterField(model_name='samplingrun', name='workspace',
            field=models.ForeignKey(default=core.tenancy.required_workspace_id, editable=False,
                on_delete=django.db.models.deletion.PROTECT, to='core.workspace', verbose_name='归属')),
    ]
