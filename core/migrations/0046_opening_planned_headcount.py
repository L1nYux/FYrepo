from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies=[('core','0045_clarify_api_reimbursement')]
    operations=[
        migrations.AddField(model_name='teamopening',name='planned_headcount',field=models.PositiveIntegerField(blank=True,null=True,verbose_name='计划招募人数')),
        migrations.AddConstraint(model_name='teamopening',constraint=models.CheckConstraint(
            condition=models.Q(planned_headcount__isnull=True)|models.Q(planned_headcount__gte=1,planned_headcount__lte=1000),name='opening_valid_headcount')),
    ]
