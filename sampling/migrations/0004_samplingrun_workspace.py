"""Bind legacy runs to their real project or original library, preserving artifacts."""
import core.tenancy
import django.db.models.deletion
from django.db import migrations, models


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


def bind_existing_runs(apps, schema_editor):
    Run = apps.get_model("sampling", "SamplingRun")
    Project = apps.get_model("core", "Project")
    Space = apps.get_model("core", "Workspace")
    Membership = apps.get_model("core", "TeamMembership")
    alias = schema_editor.connection.alias
    projects = {row["pk"]: row for row in Project.objects.using(alias).values("pk", "workspace_id", "team_id")}
    original = Space.objects.using(alias).filter(kind="team", team_id=1).first()
    original_members = set(Membership.objects.using(alias).filter(team_id=1, active=True,
        deleted_at__isnull=True, role__in=["owner", "admin", "member"]).values_list("user_id", flat=True))
    for run in Run.objects.using(alias).all().iterator():
        if run.workspace_id:
            # Existing releases already bound these records. Derive the new
            # team field from that space without moving data between owners.
            team_id = Space.objects.using(alias).get(pk=run.workspace_id).team_id
            Run.objects.using(alias).filter(pk=run.pk).update(team_id=team_id)
            continue
        project = projects.get(run.project_id)
        if project:
            workspace_id, team_id = project["workspace_id"], project["team_id"]
        elif original and run.created_by_id in original_members:
            workspace_id, team_id = original.pk, original.team_id
        else:
            personal, _ = Space.objects.using(alias).get_or_create(owner_id=run.created_by_id, defaults={"kind": "personal"})
            workspace_id, team_id = personal.pk, None
        Run.objects.using(alias).filter(pk=run.pk).update(workspace_id=workspace_id, team_id=team_id)


class Migration(migrations.Migration):
    dependencies = [("sampling", "0003_candidatepaper_cross_disciplinary_journal"),
                    ("core", "0044_documentaccess_project_required")]
    operations = [
        migrations.AlterModelOptions(name="samplingrun", options={
            "ordering": ["-created_at"], "verbose_name": "样本集", "verbose_name_plural": "样本集",
            "default_manager_name": "objects", "base_manager_name": "all_objects"}),
        migrations.AlterModelManagers(name="samplingrun", managers=[
            ("objects", models.Manager()), ("all_objects", models.Manager())]),
        migrations.AddField(model_name="samplingrun", name="team", field=models.ForeignKey(
            to="core.team", on_delete=django.db.models.deletion.PROTECT, null=True, blank=True,
            editable=False, default=core.tenancy.team_id)),
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunPython(add_workspace_if_missing, remove_workspace_if_present)],
            state_operations=[migrations.AddField(model_name="samplingrun", name="workspace", field=models.ForeignKey(
                to="core.workspace", on_delete=django.db.models.deletion.PROTECT, null=True, editable=False, verbose_name='归属'))]),
        migrations.RunPython(bind_existing_runs, migrations.RunPython.noop),
        migrations.AlterField(model_name="samplingrun", name="workspace", field=models.ForeignKey(
            to="core.workspace", on_delete=django.db.models.deletion.PROTECT, editable=False,
            default=core.tenancy.required_workspace_id, verbose_name='归属')),
    ]
