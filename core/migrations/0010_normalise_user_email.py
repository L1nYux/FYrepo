"""邮箱自助找回密码的前置数据整理。

忘记密码的流程按邮箱找人（`PasswordResetForm.get_users` 用 `email__iexact` 查询），
因此需要保证：一个邮箱只对应一个账号。

这里做两件事：

1. 把已有邮箱统一成小写，避免 `A@x.com` 与 `a@x.com` 被当成两个不同的地址。
2. 给非空邮箱加一个部分唯一索引（条件 `email != ''`）。空邮箱允许共存：
   账号是历史遗留、还没来得及填邮箱时不会互相冲突，成员下次保存资料时会被要求补上。

如果现有数据里已经存在重复邮箱，迁移会**报错停下并列出冲突的邮箱**，而不是静默改动账号归属。
这是有意的：哪个账号该保留这个邮箱需要人工判断，迁移不做决定。
"""
from django.db import migrations


def lowercase_emails(apps, schema_editor):
    User = apps.get_model('auth', 'User')
    for user in User.objects.exclude(email=''):
        lowered = user.email.strip().lower()
        if lowered != user.email:
            user.email = lowered
            user.save(update_fields=['email'])


def check_no_duplicates(apps, schema_editor):
    """加唯一索引前先把重复邮箱找出来，报错信息要能让运维直接动手。"""
    User = apps.get_model('auth', 'User')
    seen = {}
    for pk, email in User.objects.exclude(email='').values_list('pk', 'email'):
        seen.setdefault(email.lower(), []).append(pk)
    clashes = {email: pks for email, pks in seen.items() if len(pks) > 1}
    if clashes:
        detail = '；'.join(f'{email} → 账号 {pks}' for email, pks in sorted(clashes.items()))
        raise RuntimeError(
            '存在重复邮箱，无法为「邮箱自助找回密码」建立唯一索引。'
            f'请先处理这些账号的邮箱后再运行 migrate：{detail}'
        )


def create_unique_index(apps, schema_editor):
    """SQLite / PostgreSQL 都支持部分唯一索引；空邮箱不参与唯一性。"""
    schema_editor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS auth_user_email_unique_nonempty "
        "ON auth_user (email) WHERE email != ''"
    )


def drop_unique_index(apps, schema_editor):
    schema_editor.execute("DROP INDEX IF EXISTS auth_user_email_unique_nonempty")


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0009_financeentry_project_project_budget'),
    ]

    operations = [
        migrations.RunPython(lowercase_emails, migrations.RunPython.noop),
        migrations.RunPython(check_no_duplicates, migrations.RunPython.noop),
        migrations.RunPython(create_unique_index, drop_unique_index),
    ]
