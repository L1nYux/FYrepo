import re
from decimal import Decimal
from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from .models import Provider, PoolModel, PoolSettings, Allowance
from .network import validate_url
from .prices import price_values
from .automatic_prices import exchange_rate


class SimplePriceForm(forms.Form):
    currency=forms.ChoiceField(choices=[('CNY','人民币'),('USD','美元')])
    input_rate=forms.DecimalField(min_value=0,max_value=100000,decimal_places=6,max_digits=14)
    output_rate=forms.DecimalField(min_value=0,max_value=100000,decimal_places=6,max_digits=14)
    cny_exchange_rate=forms.DecimalField(required=False,min_value=Decimal('.000001'),max_value=100000,decimal_places=6,max_digits=12)

    def clean(self):
        data=super().clean()
        if data.get('currency')=='USD' and not data.get('cny_exchange_rate'):
            try: data['cny_exchange_rate']=exchange_rate()['rate']
            except Exception: raise ValidationError('汇率读取失败，请在可选设置中补充人民币汇率。') from None
        if not self.errors: data.update(price_values(data))
        return data


class ProviderForm(forms.ModelForm):
    api_key=forms.CharField(label='API Key',required=False,widget=forms.PasswordInput(render_value=False),max_length=2000,
        help_text='只保存在服务端；编辑时留空保留已有密钥。')
    class Meta:
        model=Provider
        fields=['name','protocol','base_url','key_env','enabled']

    def clean_base_url(self): return validate_url(self.cleaned_data['base_url'])

    def clean_key_env(self):
        value=self.cleaned_data.get('key_env','').strip()
        if value and not re.fullmatch(r'[A-Z][A-Z0-9_]{0,119}',value): raise ValidationError('环境变量名称需要大写字母、数字或下划线。')
        return value


class ModelForm(forms.ModelForm):
    currency=forms.ChoiceField(label='价格币种',choices=[('CNY','CNY'),('USD','USD')])
    input_rate=forms.DecimalField(label='输入单价 / 百万 token',min_value=0,max_value=100000,decimal_places=6,max_digits=14)
    output_rate=forms.DecimalField(label='输出单价 / 百万 token',min_value=0,max_value=100000,decimal_places=6,max_digits=14)
    cached_rate=forms.DecimalField(label='缓存读取单价（可选）',required=False,min_value=0,max_value=100000,decimal_places=6,max_digits=14)
    cache_write_rate=forms.DecimalField(label='缓存写入单价（可选）',required=False,min_value=0,max_value=100000,decimal_places=6,max_digits=14)
    cny_exchange_rate=forms.DecimalField(label='人民币汇率覆盖（美元，留空自动）',required=False,min_value=Decimal('.000001'),max_value=100000,decimal_places=6,max_digits=12)
    class Meta:
        model=PoolModel
        fields=['provider','model_id','label','enabled','supports_tools','max_output_tokens','output_parameter','price_feed_url','price_source']
        labels={'provider':'厂商'}

    def clean_price_feed_url(self):
        value=self.cleaned_data.get('price_feed_url','')
        return validate_url(value) if value else ''

    def clean(self):
        data=super().clean()
        if data.get('currency')=='USD' and not data.get('cny_exchange_rate'):
            try: data['cny_exchange_rate']=exchange_rate()['rate']
            except Exception: raise ValidationError('汇率读取失败，请补充人民币汇率。') from None
        if not self.errors: price_values(data)
        return data


class PointLimitsForm(forms.ModelForm):
    """Public form amounts are points; existing database amounts stay in CNY."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in list(self.fields.items()):
            if 'limit' in name or name == 'max_call_cost':
                self.fields[name] = forms.DecimalField(label=field.label.replace('元', '点'),
                    required=field.required, min_value=0, max_value=Decimal('999999999999'), decimal_places=0)
                if self.initial.get(name) is not None:
                    self.initial[name] = Decimal(str(self.initial[name])) * 100

    def clean(self):
        data = super().clean()
        for name in self.fields:
            if ('limit' in name or name == 'max_call_cost') and data.get(name) is not None:
                data[name] /= 100
        return data

    def save(self, commit=True):
        instance = super().save(commit=False)
        if commit:
            # Limit edits must not overwrite a concurrent settlement's wallet balance.
            with transaction.atomic():
                PoolSettings.objects.filter(pk=1).update(enabled=F('enabled'))
                instance.save(update_fields=self._meta.fields)
        return instance


class SettingsForm(PointLimitsForm):
    class Meta:
        model=PoolSettings
        fields=['enabled','weekly_limit','default_weekly_limit','monthly_limit','default_member_limit','max_call_cost']


class PlanForm(forms.Form):
    points = forms.DecimalField(label='每人每周点数', min_value=0,
        max_value=Decimal('999999999999'), decimal_places=0)


class PointGrantForm(forms.Form):
    points = forms.DecimalField(label='额外发放点数', min_value=Decimal('0.01'),
        max_value=Decimal('100000000'), decimal_places=2)
    grant_id = forms.UUIDField()
