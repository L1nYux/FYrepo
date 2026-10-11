"""Bind legacy runs to their real project or original library, preserving artifacts."""
import core.tenancy
import django.db.models.deletion
from django.db import migrations, models


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
        migrations.AddField(model_name="samplingrun", name="workspace", field=models.ForeignKey(
            to="core.workspace", on_delete=django.db.models.deletion.PROTECT, null=True, editable=False)),
        migrations.RunPython(bind_existing_runs, migrations.RunPython.noop),
        migrations.AlterField(model_name="samplingrun", name="workspace", field=models.ForeignKey(
            to="core.workspace", on_delete=django.db.models.deletion.PROTECT, editable=False,
            default=core.tenancy.required_workspace_id)),
    ]
