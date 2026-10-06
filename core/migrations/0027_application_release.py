from django.db import migrations, models


def copy_releases(apps, schema_editor):
    releases = apps.get_model('core', 'ApplicationRelease')
    announcements = apps.get_model('core', 'Announcement')
    for item in announcements.objects.using(schema_editor.connection.alias).exclude(release_version__isnull=True).exclude(release_version='').order_by('created_at', 'pk').iterator():
        release,created=releases.objects.using(schema_editor.connection.alias).get_or_create(release_version=item.release_version, defaults={
            'title':item.title, 'body':item.body, 'release_data':item.release_data,
        })
        if created:releases.objects.using(schema_editor.connection.alias).filter(pk=release.pk).update(created_at=item.created_at)


class Migration(migrations.Migration):
    dependencies = [('core', '0026_personal_messages_team_groups')]
    operations = [
        migrations.CreateModel(name='ApplicationRelease', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('release_version', models.CharField(max_length=40, unique=True)),
            ('release_data', models.JSONField(default=dict, editable=False)),
            ('title', models.CharField(max_length=160)),
            ('body', models.TextField(max_length=5000)),
            ('created_at', models.DateTimeField(auto_now_add=True)),
        ], options={'ordering':['-created_at','-pk']}),
        migrations.RunPython(copy_releases, migrations.RunPython.noop),
    ]
