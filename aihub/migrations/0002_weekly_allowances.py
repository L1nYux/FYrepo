from decimal import Decimal
from datetime import timedelta
from zoneinfo import ZoneInfo
from django.db import migrations, models
from django.core.validators import MinValueValidator
import django.db.models.deletion


def backfill_weeks(apps,schema_editor):
    Call=apps.get_model('aihub','Call'); Week=apps.get_model('aihub','BudgetWeek')
    buckets={}; alias=schema_editor.connection.alias
    for call in Call.objects.using(alias).all().iterator():
        day=call.created_at.astimezone(ZoneInfo('Asia/Shanghai')).date()
        week=day-timedelta(days=day.weekday())
        Call.objects.using(alias).filter(pk=call.pk).update(budget_week=week)
        for scope in ('team','user:'+str(call.user_id)):
            row=buckets.setdefault((scope,week),{'spent':Decimal('0'),'reserved':Decimal('0')})
            if call.status in ('success','failed'): row['spent']+=call.cost_cny or Decimal('0')
            elif call.status in ('running','unknown'): row['reserved']+=call.reserved_cny
    for (scope,week),values in buckets.items(): Week.objects.using(alias).create(scope=scope,week=week,**values)


class Migration(migrations.Migration):
    dependencies=[('aihub','0001_initial')]
    operations=[
        migrations.AddField('poolsettings','weekly_limit',models.DecimalField('团队每周额度（元，留空不限制）',max_digits=12,decimal_places=2,null=True,blank=True,validators=[MinValueValidator(Decimal('0'))])),
        migrations.AddField('poolsettings','default_weekly_limit',models.DecimalField('成员默认每周额度（元，留空不限制）',max_digits=12,decimal_places=2,null=True,blank=True,validators=[MinValueValidator(Decimal('0'))])),
        migrations.AddField('allowance','weekly_limit',models.DecimalField('每周额度（元，留空不限制）',max_digits=12,decimal_places=2,null=True,blank=True,validators=[MinValueValidator(Decimal('0'))])),
        migrations.AddField('allowance','preferred_model',models.ForeignKey(to='aihub.poolmodel',on_delete=django.db.models.deletion.SET_NULL,null=True,blank=True,related_name='+')),
        migrations.AddField('budgetmonth','reset_credit',models.DecimalField(max_digits=18,decimal_places=8,default=0)),
        migrations.AddField('budgetmonth','reset_at',models.DateTimeField(null=True,blank=True)),
        migrations.AddField('call','budget_week',models.DateField(null=True,blank=True)),
        migrations.CreateModel(name='BudgetWeek',fields=[
            ('id',models.BigAutoField(primary_key=True,serialize=False,auto_created=True,verbose_name='ID')),
            ('scope',models.CharField(max_length=60)),('week',models.DateField()),
            ('spent',models.DecimalField(max_digits=18,decimal_places=8,default=0)),
            ('reserved',models.DecimalField(max_digits=18,decimal_places=8,default=0)),
            ('reset_credit',models.DecimalField(max_digits=18,decimal_places=8,default=0)),
            ('reset_at',models.DateTimeField(null=True,blank=True)),
        ],options={'constraints':[models.UniqueConstraint(fields=['scope','week'],name='pool_unique_week_budget')]}),
        migrations.RunPython(backfill_weeks,migrations.RunPython.noop),
    ]
