from django.db import migrations
from django.db.models import Q


def existing_results(apps, schema_editor):
    experiment=apps.get_model('core','Experiment')
    experiment.objects.using(schema_editor.connection.alias).filter(~Q(result=''),status='design').update(status='completed')


class Migration(migrations.Migration):
    dependencies=[('core','0020_experimentrun_sticker_alter_announcement_options_and_more')]
    operations=[migrations.RunPython(existing_results,migrations.RunPython.noop)]
