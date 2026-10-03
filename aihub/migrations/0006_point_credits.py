# Shared weekly plan and supplemental credits; preserve existing billing and keys.

import django.core.validators
import django.db.models.deletion
import uuid
from decimal import Decimal
from django.conf import settings
from django.db import migrations, models


def initialize_plan(apps, schema_editor):
    config = apps.get_model('aihub', 'PoolSettings')
    # The old optional per-member plan is now a single team plan. Only fill an
    # absent plan; preserve any amount the owner already explicitly configured.
    config.objects.using(schema_editor.connection.alias).filter(default_weekly_limit__isnull=True).update(default_weekly_limit=Decimal('10'))


class Migration(migrations.Migration):

    dependencies = [
        ('aihub', '0005_history_and_rate_limits'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='allowance',
            name='extra_balance',
            field=models.DecimalField(decimal_places=8, default=0, max_digits=18, verbose_name='额外额度余额（元）'),
        ),
        migrations.AddField(
            model_name='allowance',
            name='extra_reserved',
            field=models.DecimalField(decimal_places=8, default=0, max_digits=18, verbose_name='额外额度预留（元）'),
        ),
        migrations.AddField(
            model_name='call',
            name='extra_cost_cny',
            field=models.DecimalField(blank=True, decimal_places=8, max_digits=18, null=True),
        ),
        migrations.AddField(
            model_name='call',
            name='extra_reserved_cny',
            field=models.DecimalField(decimal_places=8, default=0, max_digits=18),
        ),
        migrations.AlterField(
            model_name='allowance',
            name='monthly_limit',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True, validators=[django.core.validators.MinValueValidator(Decimal('0'))], verbose_name='每月额度（元）'),
        ),
        migrations.AlterField(
            model_name='poolsettings',
            name='default_member_limit',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True, validators=[django.core.validators.MinValueValidator(Decimal('0'))], verbose_name='成员默认每月额度（元）'),
        ),
        migrations.AlterField(
            model_name='poolsettings',
            name='default_weekly_limit',
            field=models.DecimalField(blank=True, decimal_places=2, default=10, max_digits=12, null=True, validators=[django.core.validators.MinValueValidator(Decimal('0'))], verbose_name='成员默认每周额度（元，留空不限制）'),
        ),
        migrations.AlterField(
            model_name='poolsettings',
            name='monthly_limit',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True, validators=[django.core.validators.MinValueValidator(Decimal('0'))], verbose_name='团队每月额度（元）'),
        ),
        migrations.CreateModel(
            name='PointGrant',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('amount_cny', models.DecimalField(decimal_places=8, max_digits=18, validators=[django.core.validators.MinValueValidator(Decimal('0'))])),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('issued_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='point_grants', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.RunPython(initialize_plan, migrations.RunPython.noop),
    ]
