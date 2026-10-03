"""Repair physical omissions from early copies without rewriting applied history."""
from django.db import migrations


def repair(apps, schema_editor):
    connection = schema_editor.connection
    presence = apps.get_model('core', 'UserPresence')
    experiment = apps.get_model('core', 'Experiment')
    tables = set(connection.introspection.table_names())
    if presence._meta.db_table not in tables:
        schema_editor.create_model(presence)
    if experiment._meta.db_table not in tables:
        raise RuntimeError('实验表缺失，升级停止；请从备份恢复，不要伪造迁移记录。')
    with connection.cursor() as cursor:
        columns = {c.name for c in connection.introspection.get_table_description(cursor, experiment._meta.db_table)}
    if 'content' not in columns:
        schema_editor.add_field(experiment, experiment._meta.get_field('content'))
    with connection.cursor() as cursor:
        columns = {c.name for c in connection.introspection.get_table_description(cursor, presence._meta.db_table)}
        constraints = connection.introspection.get_constraints(cursor, presence._meta.db_table)
    if not {'id', 'last_seen', 'user_id'} <= columns:
        raise RuntimeError('在线状态表结构不完整，升级停止；请核对旧版本，不自动丢弃现有记录。')
    if not any(c.get('unique') and c.get('columns') == ['user_id'] for c in constraints.values()):
        raise RuntimeError('在线状态表缺少账户唯一约束，升级停止；请核对旧版本。')
    user_table = presence._meta.get_field('user').remote_field.model._meta.db_table
    if not any(c.get('foreign_key') == (user_table, 'id') and c.get('columns') == ['user_id'] for c in constraints.values()):
        raise RuntimeError('在线状态表缺少账户关联约束，升级停止；请核对旧版本。')


class Migration(migrations.Migration):
    dependencies = [('core', '0014_restore_email_unique')]
    operations = [migrations.RunPython(repair, migrations.RunPython.noop)]
