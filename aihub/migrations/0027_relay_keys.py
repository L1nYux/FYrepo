from decimal import Decimal
from django.core.validators import MinValueValidator
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('aihub', '0026_assistant_execution')]
    operations = [
        migrations.AddField(model_name='membertoken', name='expires_at', field=models.DateTimeField(null=True, blank=True)),
        migrations.AddField(model_name='membertoken', name='allowed_models', field=models.JSONField(default=list, blank=True)),
        migrations.AddField(model_name='membertoken', name='cost_limit_cny', field=models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(Decimal('0'))])),
        migrations.AddField(model_name='membertoken', name='last_used_at', field=models.DateTimeField(null=True, blank=True)),
        migrations.AddField(model_name='call', name='api_token', field=models.ForeignKey(to='aihub.membertoken', on_delete=django.db.models.deletion.PROTECT, null=True, blank=True, related_name='calls')),
        migrations.AddField(model_name='budgetmonth', name='generation', field=models.PositiveBigIntegerField(default=0)),
        migrations.AddField(model_name='budgetweek', name='generation', field=models.PositiveBigIntegerField(default=0)),
        migrations.AddField(model_name='call', name='quota_generations', field=models.JSONField(default=dict, editable=False)),
    ]
