"""Import accounts from a read-only SQLite backup into a newly migrated database."""
import sqlite3
from datetime import timezone as datetime_timezone
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import Group, Permission, User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.dateparse import parse_datetime
from django.utils import timezone

from core.models import MemberProfile


class Command(BaseCommand):
    help = '将旧 SQLite 备份的账号及密码摘要导入新空库，不导入业务数据。'

    def add_arguments(self, parser):
        parser.add_argument('--source', required=True)

    def handle(self, *args, **options):
        path = Path(options['source']).resolve()
        destination = Path(settings.DATABASES['default']['NAME']).resolve()
        if not path.is_file() or path == destination:
            raise CommandError('源文件必须是另一份已存在的 SQLite 数据库。')
        if User.objects.exists():
            raise CommandError('目标数据库已有账号，拒绝覆盖。请使用新空库。')
        source = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
        source.row_factory = sqlite3.Row
        try:
            tables = {r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'auth_user' not in tables:
                raise CommandError('源数据库没有 Django 用户表。')
            users = list(source.execute('SELECT * FROM auth_user'))
            if not users or not any(r['is_staff'] and r['is_active'] for r in users):
                raise CommandError('源数据库没有有效管理员，停止导入。')
            fields = {f.attname for f in User._meta.concrete_fields}
            with transaction.atomic():
                imported = []
                for row in users:
                    values = {k:row[k] for k in row.keys() if k in fields}
                    # 邮箱统一小写：bulk_create 不触发 pre_save 信号，这里自己规范化，
                    # 保证「忘记密码」按邮箱找人时一个邮箱只对应一个账号。
                    if values.get('email'):
                        values['email'] = values['email'].strip().lower()
                    # Django stores USE_TZ SQLite datetimes as naive UTC strings.
                    for key in ('last_login', 'date_joined'):
                        if values.get(key):
                            value = parse_datetime(values[key])
                            if value is None:
                                raise CommandError('源账号时间字段格式无效，导入已回滚。')
                            if settings.USE_TZ and timezone.is_naive(value):
                                value = value.replace(tzinfo=datetime_timezone.utc)
                            values[key] = value
                    imported.append(User(**values))
                User.objects.bulk_create(imported)
                if 'core_memberprofile' in tables:
                    for row in source.execute('SELECT user_id, tier FROM core_memberprofile'):
                        MemberProfile.objects.create(user_id=row['user_id'], tier=row['tier'])
                group_map = {}
                if 'auth_group' in tables:
                    for row in source.execute('SELECT id, name FROM auth_group'):
                        group_map[row['id']] = Group.objects.get_or_create(name=row['name'])[0]
                if 'auth_user_groups' in tables:
                    for row in source.execute('SELECT user_id, group_id FROM auth_user_groups'):
                        group_map[row['group_id']].user_set.add(row['user_id'])
                for table, owner, relation in [('auth_group_permissions','group_id','permissions'),('auth_user_user_permissions','user_id','user_permissions')]:
                    if table not in tables:
                        continue
                    query = f'SELECT x.{owner} AS owner_id, p.codename, c.app_label, c.model FROM {table} x JOIN auth_permission p ON p.id=x.permission_id JOIN django_content_type c ON c.id=p.content_type_id'
                    for row in source.execute(query):
                        permission = Permission.objects.filter(codename=row['codename'], content_type__app_label=row['app_label'], content_type__model=row['model']).first()
                        if permission is None:
                            raise CommandError('存在无法映射的自定义权限；导入已回滚，请先处理权限映射。')
                        obj = group_map[row['owner_id']] if owner == 'group_id' else User.objects.get(pk=row['owner_id'])
                        getattr(obj, relation).add(permission)
                for row in users:
                    account = User.objects.get(pk=row['id'])
                    if account.password != row['password'] or account.is_staff != bool(row['is_staff']) or account.is_superuser != bool(row['is_superuser']):
                        raise CommandError('账号保留校验失败，导入已回滚。')
        finally:
            source.close()
        self.stdout.write(self.style.SUCCESS(f'已导入 {len(users)} 个账号，原密码摘要和管理员权限已保留。'))
