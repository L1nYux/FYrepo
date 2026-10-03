"""Restore the email index after auth's SQLite table rebuilds."""
from django.db import migrations


def restore_index(apps, schema_editor):
    User = apps.get_model('auth', 'User')
    users = User.objects.using(schema_editor.connection.alias)
    seen = {}
    for pk, email in users.values_list('pk', 'email'):
        normalized = email.strip().lower()
        if normalized:
            seen.setdefault(normalized, []).append(pk)
    conflicts = {email: ids for email, ids in seen.items() if len(ids) > 1}
    if conflicts:
        detail = '；'.join(f'{email} → 账号 {ids}' for email, ids in sorted(conflicts.items()))
        raise RuntimeError('邮箱重复，升级已停止；请先处理重复邮箱后再迁移：' + detail)
    for pk, email in users.values_list('pk', 'email'):
        normalized = email.strip().lower()
        if email != normalized:
            users.filter(pk=pk).update(email=normalized)
    schema_editor.execute('DROP INDEX IF EXISTS auth_user_email_unique_nonempty')
    schema_editor.execute("CREATE UNIQUE INDEX auth_user_email_unique_nonempty "
                          "ON auth_user (LOWER(TRIM(email))) WHERE TRIM(email) != ''")


class Migration(migrations.Migration):
    dependencies = [('core', '0013_message_actions'), ('auth', '0012_alter_user_first_name_max_length')]
    operations = [migrations.RunPython(restore_index, migrations.RunPython.noop)]
