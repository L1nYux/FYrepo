"""成果与留言可以挂在项目上。

- 成果（Submission）除了挂在任务上，也可以直接挂在项目上，用于结题报告这类不属于单个任务的产出。
- 留言（Comment）可以对任务、项目或某一份成果留言。
- 两者都用数据库约束保证「有且只有一个归属」。

既有数据无需搬迁：原来的成果都挂在任务上，原来的留言都挂在任务上；只有「针对成果的留言」
过去同时记录了任务，这里按新规则清掉多余的归属。

生成方式：按模型差异手工编写。改动模型后请用
`manage.py makemigrations --check --dry-run` 确认没有遗漏。
"""

import django.db.models.deletion
from django.db import migrations, models


def drop_redundant_comment_targets(apps, schema_editor):
    """针对成果的留言只保留成果归属，去掉同时记录的任务／项目归属。"""
    Comment = apps.get_model('core', 'Comment')
    Comment.objects.filter(submission__isnull=False).update(task=None, project=None)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_project_tree_discussions_finance'),
    ]

    operations = [
        migrations.AddField(
            model_name='submission',
            name='project',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name='submissions', to='core.project', verbose_name='项目'),
        ),
        migrations.AlterField(
            model_name='submission',
            name='task',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name='submissions', to='core.task', verbose_name='任务'),
        ),
        migrations.AlterModelOptions(
            name='submission',
            options={'ordering': ['-created_at'], 'verbose_name': '成果', 'verbose_name_plural': '成果'},
        ),
        migrations.AddConstraint(
            model_name='submission',
            constraint=models.CheckConstraint(
                condition=(models.Q(task__isnull=False, project__isnull=True)
                           | models.Q(task__isnull=True, project__isnull=False)),
                name='submission_has_one_target'),
        ),
        migrations.AddField(
            model_name='comment',
            name='project',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE,
                                    related_name='comments', to='core.project', verbose_name='项目'),
        ),
        migrations.AlterField(
            model_name='comment',
            name='task',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE,
                                    related_name='comments', to='core.task', verbose_name='任务'),
        ),
        migrations.AlterModelOptions(
            name='comment',
            options={'ordering': ['created_at'], 'verbose_name': '留言', 'verbose_name_plural': '留言'},
        ),
        migrations.RunPython(drop_redundant_comment_targets, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='comment',
            constraint=models.CheckConstraint(
                condition=(models.Q(task__isnull=False, project__isnull=True, submission__isnull=True)
                           | models.Q(task__isnull=True, project__isnull=False, submission__isnull=True)
                           | models.Q(task__isnull=True, project__isnull=True, submission__isnull=False)),
                name='comment_has_one_target'),
        ),
    ]
