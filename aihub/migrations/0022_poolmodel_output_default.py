from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('aihub', '0021_membertoken_optional_project')]
    operations = [migrations.AlterField(
        model_name='poolmodel', name='max_output_tokens',
        field=models.PositiveIntegerField(default=32768,
            validators=[MinValueValidator(64), MaxValueValidator(32768)],
            verbose_name='最大输出 token'))]
