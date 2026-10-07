import json
from decimal import Decimal, InvalidOperation
from django.utils import timezone
from django.db import transaction
from django.core.exceptions import ValidationError
from .models import PoolModel, PriceVersion, DailyPrice
from .network import json_request
from .automatic_prices import automatic_price, AUTO

RATE_FIELDS=('input_rate','output_rate','cached_rate','cache_write_rate','cny_exchange_rate')


def current_price(model, at=None):
    return model.prices.filter(effective_from__lte=at or timezone.now()).first()


def price_values(data):
    values={}
    try:
        for name in RATE_FIELDS:
            raw=data.get(name)
            if raw is None and name in ('cached_rate','cache_write_rate'): raw=data.get('input_rate')
            if raw is None and name=='cny_exchange_rate' and data.get('currency','CNY')=='CNY': raw='1'
            number=Decimal(str(raw))
            if not number.is_finite() or number<0 or number>100000: raise ValueError
            if name=='cny_exchange_rate' and number<=0: raise ValueError
            values[name]=number.quantize(Decimal('0.000001'))
        values['currency']=data.get('currency','CNY')
        if values['currency'] not in ('CNY','USD'): raise ValueError
        if values['currency']=='CNY': values['cny_exchange_rate']=Decimal('1')
    except (InvalidOperation,ValueError,TypeError):
        raise ValidationError('价格或汇率无效，请填非负单价及正汇率。')
    return values


def save_price(model, data, source=''):
    values=price_values(data)
    with transaction.atomic():
        # Acquire the model row before checking the current version (SQLite also serializes writers).
        PoolModel.objects.filter(pk=model.pk).update(enabled=model.enabled)
        previous=current_price(model)
        if previous and all(getattr(previous,k)==v for k,v in values.items()) and previous.source==source:
            return previous
        return PriceVersion.objects.create(model=model,effective_from=timezone.now(),source=source[:500],**values)


def refresh_prices(force=False):
    day=timezone.localdate(); count=0
    for model in PoolModel.objects.filter(enabled=True,provider__enabled=True).select_related('provider'):
        if not force and DailyPrice.objects.filter(model=model,day=day).exists(): continue
        price=current_price(model); status='manual'; note='沿用管理员登记价格，未连接自动价格源。'
        if model.price_feed_url:
            try:
                feed=json_request(model.price_feed_url,timeout=12)
                if feed.get('model') != model.model_id: raise ValueError('wrong model')
                price=save_price(model,feed,model.price_feed_url)
                status='verified'; note='从指定 JSON 价格源核对。'
            except Exception:
                status='failed'; note='价格源更新失败；保留最近有效价格，请检查来源。'
        elif price is None or price.source.startswith((AUTO,'官方 Flash 高峰参考价')):
            try:
                data=automatic_price(model.provider,model.model_id)
                if data:
                    price=save_price(model,data,data['source']); status='verified'
                    note='已核对公开价格源；人民币折算为估算，供应商账单为准。'
                elif price is None:
                    from .vendor_prices import source_info
                    info=source_info(model.provider)
                    status='failed'; note='官方价格来源未列出此型号，请核对 ID 或手动登记。' if info['supported'] else info['note']
            except Exception:
                status='failed'; note='自动读取失败；保留最近有效价格。'
        DailyPrice.objects.update_or_create(model=model,day=day,defaults={'price':price,'status':status,'note':note})
        count+=1
    return count
