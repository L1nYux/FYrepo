"""账号层级档案与聊天室消息。

- MemberProfile：区分「开发者」和「普通用户」。管理员仍由 User.is_staff 表示。
  没有档案的账号一律按开发者处理，所以升级前的既有账号（邀请码注册的开发者、
  createsuperuser 建的管理员）行为完全不变，本迁移不需要搬移任何数据。
- ChatMessage：开发者聊天室与公共聊天室共用一张表，靠 room 区分。新表，无历史数据。

生成方式：按模型差异手工编写。改动模型后请用
`manage.py makemigrations --check --dry-run` 确认没有遗漏。
"""

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('core', '0003_results_and_comments_on_projects'),
    ]

    operations = [
        migrations.CreateModel(
            name='MemberProfile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tier', models.CharField(choices=[('developer', '开发者'), ('normal', '普通用户')],
                                          default='developer', max_length=12, verbose_name='账号层级')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE,
                                              related_name='member_profile',
                                              to=settings.AUTH_USER_MODEL, verbose_name='账号')),
            ],
            options={
                'verbose_name': '账号档案',
                'verbose_name_plural': '账号档案',
            },
        ),
        migrations.CreateModel(
            name='ChatMessage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('room', models.CharField(choices=[('public', '公共聊天室'), ('developers', '开发者聊天室')],
                                          default='public', max_length=12, verbose_name='聊天室')),
                ('body', models.TextField(max_length=2000, verbose_name='内容')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='发言时间')),
                ('author', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                             related_name='chat_messages',
                                             to=settings.AUTH_USER_MODEL, verbose_name='发言人')),
            ],
            options={
                'verbose_name': '聊天室消息',
                'verbose_name_plural': '聊天室消息',
                'ordering': ['created_at'],
            },
        ),
    ]
