from django.db import migrations, models
import django.db.models.deletion
import core.tenancy


def add_workspace_if_missing(apps, schema_editor):
    Run = apps.get_model('sampling', 'SamplingRun')
    columns = {column.name for column in schema_editor.connection.introspection.get_table_description(
        schema_editor.connection.cursor(), Run._meta.db_table)}
    if 'workspace_id' not in columns:
        field = models.ForeignKey(apps.get_model('core', 'Workspace'), null=True,
            editable=False, on_delete=django.db.models.deletion.PROTECT, verbose_name='归属')
        field.set_attributes_from_name('workspace')
        schema_editor.add_field(Run, field)


def remove_workspace_if_present(apps, schema_editor):
    Run = apps.get_model('sampling', 'SamplingRun')
    columns = {column.name for column in schema_editor.connection.introspection.get_table_description(
        schema_editor.connection.cursor(), Run._meta.db_table)}
    if 'workspace_id' in columns:
        field = models.ForeignKey(apps.get_model('core', 'Workspace'), null=True,
            editable=False, on_delete=django.db.models.deletion.PROTECT)
        field.set_attributes_from_name('workspace')
        if not any(existing.name == 'workspace' for existing in Run._meta.fields):
            Run.add_to_class('workspace', field)
        else:
            field = Run._meta.get_field('workspace')
        schema_editor.remove_field(Run, field)


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
        # PR #10 and the prior release introduced this field independently.
        # Preserve both migration records; an already-created column is reused.
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunPython(add_workspace_if_missing, remove_workspace_if_present)],
            state_operations=[migrations.AddField(model_name='samplingrun', name='workspace',
                field=models.ForeignKey(null=True, editable=False, on_delete=django.db.models.deletion.PROTECT,
                                        to='core.workspace', verbose_name='归属'))]),
        migrations.RunPython(assign_legacy_runs, migrations.RunPython.noop),
        migrations.AlterField(model_name='samplingrun', name='workspace',
            field=models.ForeignKey(default=core.tenancy.required_workspace_id, editable=False,
                on_delete=django.db.models.deletion.PROTECT, to='core.workspace', verbose_name='归属')),
    ]
