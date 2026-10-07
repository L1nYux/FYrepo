import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from decimal import Decimal
from unittest.mock import patch
from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from .automatic_prices import automatic_price, enrich_catalog
from .vendor_prices import (source_info, rate, markdown_prices, bailian_html_prices, bailian_api_prices,
                            official_prices, PriceUnavailable, QWEN_URL, GLM_URL, MINIMAX_CN_URL, MINIMAX_US_URL)
from .models import Provider, PoolModel, PoolSettings, PriceVersion, DailyPrice
from .prices import refresh_prices


# Small synthetic examples of documented structures; no real keys or API calls.
GLM = '''
| 模型名称 | 上下文 | 输入单价（元/百万 Tokens） | 输出单价（元/百万 Tokens） | 缓存存储（元/百万 Tokens/小时） | 缓存命中（元/百万 Tokens） |
| - | - | - | - | - | - |
| GLM-5.3-Flash | 1M | 0.8 | 2.8 | 限时免费 | 0.23 |
| GLM-5.3-FlashX | 1M | 2 | 7 | 限时免费 | 0.57 |
| GLM-5.1 | 输入长度 [0, 32K) | 6 | 24 | 限时免费 | 1.3 |
| GLM-5.1 | 输入长度 ≥32K | 8 | 28 | 限时免费 | 2 |
| GLM-4.7-Flash | 200K | 免费 | 免费 | 限时免费 | 免费 |
| GLM-Unlisted | 200K | 待定 | 待定 | 限时免费 | 不支持 |
| 模型名称 | 规格 | 单价 |
| - | - | - |
| GLM-Image | 图片 | 0.1 元/次 |
'''

MINIMAX = '''
<Tabs>
<Tab title="标准">
| **模型** | **输入价格**<br /> 元/百万 tokens | **输出价格**<br /> 元/百万 tokens | **缓存读取**<br /> 元/百万 tokens |
| - | - | - | - |
| **MiniMax-M3**<br />≤ 512k 输入 tokens | ~~4.20~~ 2.10 | ~~16.80~~ 8.40 | ~~0.84~~ 0.42 |
| **MiniMax-M3**<br />> 512k 输入 tokens | ~~8.40~~ 4.20 | ~~33.60~~ 16.80 | ~~1.68~~ 0.84 |
</Tab>
<Tab title="优先*">
| **模型** | **输入价格**<br /> 元/百万 tokens | **输出价格**<br /> 元/百万 tokens | **缓存读取**<br /> 元/百万 tokens |
| - | - | - | - |
| **MiniMax-M3**<br />≤ 512k 输入 tokens | 6.3 | 25.2 | 1.26 |
</Tab>
</Tabs>
| **模型** | **输入价格**<br /> 元/百万 tokens | **输出价格**<br /> 元/百万 tokens | **缓存读取**<br /> 元/百万 tokens | **缓存写入**<br /> 元/百万 tokens |
| - | - | - | - | - |
| **MiniMax-M2.7** | 2.1 | 8.4 | 0.42 | 2.625 |
| **MiniMax-M2.7-highspeed** | 4.2 | 16.8 | 0.42 | 2.625 |
'''

MINIMAX_US = '''
| Model | Input | Output | Prompt caching Read | Prompt caching Write |
| - | - | - | - | - |
| MiniMax-M2.7 | $0.3 / M tokens | $1.2 / M tokens | $0.06 / M tokens | $0.375 / M tokens |
'''

QWEN = '''
<script>"<h4>华北2（北京）</h4><table><tr><td>Not a price</td></tr></table>"</script>
<h3>千问 Flash</h3><h4>华北2（北京）</h4>
<table><tr><th>模型 ID</th><th>单次请求的输入Token数</th><th>输入单价（每百万 Token）</th><th>输出单价（每百万 Token）</th><th>免费额度</th></tr>
<tr><td>qwen3.8-flash</td><td>0&lt;Token≤1M</td><td>0.8元</td><td>2.7元</td><td>100万Token</td></tr>
<tr><td rowspan="2">qwen3.7-plus<blockquote>当前能力等同于其他型号</blockquote></td><td>0&lt;Token≤256K</td><td>原价2元（限时8折）</td><td>原价8元（限时8折）</td><td rowspan="2">100万Token</td></tr>
<tr><td>256K&lt;Token≤1M</td><td>6元</td><td>24元</td></tr>
<tr><td>qwen-unrecognized</td><td>1M</td><td>需咨询</td><td>需咨询</td><td>100万Token</td></tr></table>
<table><tr><th>模型 ID</th><th>服务部署范围</th><th>输入单价（每百万 Token）</th><th>输出单价（每百万 Token）</th></tr>
<tr><td>qwen3.8-flash</td><td>全球</td><td>20元</td><td>80元</td></tr></table>
<h4>新加坡</h4><table><tr><th>模型 ID</th><th>输入单价（每百万 Token）</th><th>输出单价（每百万 Token）</th></tr>
<tr><td>qwen3.8-flash</td><td>10元</td><td>40元</td></tr></table>
<h3>图片</h3><h4>华北2（北京）</h4><table><tr><th>模型 ID</th><th>单价（每张）</th></tr><tr><td>qwen-image</td><td>0.02元</td></tr></table>
'''


def api_row(identifier='qwen3.8-flash', input_rate='0.8', output_rate='2.7'):
    return {'success': True, 'output': {'total': 1, 'models': [{'model': identifier, 'prices': [
        {'range_name': 'Default', 'prices': [{'type': 'input_token', 'price': input_rate, 'price_unit': '每百万tokens'},
                                           {'type': 'output_token', 'price': output_rate, 'price_unit': '每百万tokens'}]}]}]}}


class OfficialPriceParsingTests(SimpleTestCase):
    def setUp(self): cache.clear()
    def tearDown(self): cache.clear()

    def test_glm_prices_cache_hit_free_and_tier_max(self):
        values=markdown_prices(GLM,'glm','CNY',GLM_URL)
        self.assertEqual(values['glm-5.3-flash']['cached_rate'],'0.23')
        self.assertEqual(values['glm-5.3-flashx']['output_rate'],'7')
        self.assertEqual(values['glm-5.1']['input_rate'],'8')
        self.assertIn('最高档',values['glm-5.1']['source'])
        self.assertEqual(values['glm-4.7-flash']['output_rate'],'0')
        self.assertNotIn('glm-unlisted',values);self.assertNotIn('glm-image',values)

    def test_minimax_discount_tiers_and_priority_do_not_mix(self):
        values=markdown_prices(MINIMAX,'minimax','CNY',MINIMAX_CN_URL)
        self.assertEqual(Decimal(values['minimax-m3']['input_rate']),Decimal('4.2'))
        self.assertEqual(values['minimax-m2.7']['cache_write_rate'],'2.625')
        self.assertEqual(values['minimax-m2.7-highspeed']['cached_rate'],'0.42')

    def test_minimax_international_units(self):
        values=markdown_prices(MINIMAX_US,'minimax','USD',MINIMAX_US_URL)
        self.assertEqual(values['minimax-m2.7']['input_rate'],'0.3')
        self.assertEqual(values['minimax-m2.7']['currency'],'USD')

    def test_bailian_region_scope_rowspan_and_gift_do_not_mix(self):
        values=bailian_html_prices(QWEN)
        self.assertEqual(values['qwen3.8-flash']['input_rate'],'0.8')
        self.assertEqual(values['qwen3.8-flash']['output_rate'],'2.7')
        self.assertEqual(values['qwen3.7-plus']['input_rate'],'6')
        self.assertIn('最高档',values['qwen3.7-plus']['source'])
        self.assertEqual(set(values),{'qwen3.8-flash','qwen3.7-plus'})

    def test_changed_units_or_broken_layout_fail_closed(self):
        for text in (GLM.replace('元/百万 Tokens','美元/千 Tokens'),'<html>login</html>'):
            with self.assertRaises(PriceUnavailable): markdown_prices(text,'glm','CNY',GLM_URL)
        with self.assertRaises(PriceUnavailable): bailian_html_prices(QWEN.replace('每百万 Token','每千 Token'))
        for value in ('NaN','-1','100001','0.2美元/千token','1或2'):
            with self.subTest(value=value),self.assertRaises(ValueError): rate(value)

    def test_api_unit_and_media_validation(self):
        values=bailian_api_prices(api_row())
        self.assertEqual(values['qwen3.8-flash']['input_rate'],'0.8')
        data=api_row();data['output']['models'][0]['prices'][0]['prices'][1]['price_unit']='每张'
        self.assertEqual(bailian_api_prices(data),{})
        with self.assertRaises(ValueError): bailian_api_prices({'success':False})

    def test_host_and_region_detection_reject_spoofs(self):
        for host in ('open.bigmodel.cn.evil.test','api.minimax.io.evil.test','evil.cn-beijing.maas.aliyuncs.com.evil.test','coding.dashscope.aliyuncs.com'):
            self.assertFalse(source_info(SimpleNamespace(base_url='https://'+host+'/v1'))['supported'])
        self.assertTrue(source_info(SimpleNamespace(base_url='https://workspace1.cn-beijing.maas.aliyuncs.com/compatible-mode/v1'))['supported'])

    @patch('aihub.vendor_prices.text_request',return_value=GLM)
    def test_public_prices_do_not_receive_keys_and_are_cached(self,read):
        provider=SimpleNamespace(base_url='https://open.bigmodel.cn/api/paas/v4')
        values=official_prices(provider,key='do-not-send-this')
        self.assertIn('glm-5.3-flash',values)
        official_prices(provider);read.assert_called_once_with(GLM_URL+'.md')
        official_prices(provider,force=True);self.assertEqual(read.call_count,2)

    @patch('aihub.vendor_prices.text_request',return_value=QWEN)
    @patch('aihub.vendor_prices.json_request',return_value=api_row())
    def test_workspace_uses_fixed_official_endpoint_and_keeps_key_private(self,read,public):
        provider=SimpleNamespace(base_url='https://workspace1.cn-beijing.maas.aliyuncs.com/compatible-mode/v1')
        values=official_prices(provider,key='test-key')
        url=read.call_args.args[0]
        self.assertTrue(url.startswith('https://workspace1.cn-beijing.maas.aliyuncs.com/api/v1/models?'))
        self.assertIn('service_site=asia-pacific-china',url)
        self.assertEqual(read.call_args.kwargs['headers'],{'Authorization':'Bearer test-key'})
        self.assertNotIn('test-key',json.dumps(values));public.assert_not_called()

    @patch('aihub.vendor_prices.text_request',return_value=QWEN)
    @patch('aihub.vendor_prices.json_request',side_effect=RuntimeError('simulated failure'))
    def test_workspace_api_failure_uses_identified_public_tariff(self,read,public):
        values=official_prices(SimpleNamespace(base_url='https://workspace1.cn-beijing.maas.aliyuncs.com/v1'),key='test-key')
        self.assertIn(QWEN_URL,values['qwen3.8-flash']['source'])
        public.assert_called_once_with(QWEN_URL)

    @patch('aihub.vendor_prices.text_request',return_value=MINIMAX_US)
    @patch('aihub.automatic_prices.exchange_rate',return_value={'rate':'7','day':'2026-10-04'})
    def test_usd_price_enrichment_has_explicit_exchange_rate(self,fx,read):
        provider=SimpleNamespace(base_url='https://api.minimax.io/v1')
        value=automatic_price(provider,'MiniMax-M2.7')
        self.assertEqual(value['input_rate'],'0.3');self.assertEqual(value['cny_exchange_rate'],'7')
        rows=[{'id':'MiniMax-M2.7','price':None}]
        note,exchange=enrich_catalog(provider,rows)
        self.assertEqual(rows[0]['price']['currency'],'USD');self.assertIn('M Plan',note)
        self.assertEqual(exchange['rate'],'7')

    @patch('aihub.vendor_prices.text_request',return_value=MINIMAX_US)
    @patch('aihub.automatic_prices.exchange_rate',side_effect=RuntimeError('simulated'))
    def test_exchange_failure_is_identified_and_not_a_zero_price(self,fx,read):
        with self.assertRaisesMessage(PriceUnavailable,'汇率读取失败'):
            automatic_price(SimpleNamespace(base_url='https://api.minimax.io/v1'),'MiniMax-M2.7')


class OfficialPriceViewTests(TestCase):
    from core.testing_ownership import TeamFixtureClient
    client_class = TeamFixtureClient
    def setUp(self):
        cache.clear()
        self.owner=User.objects.create_user('price-owner',is_staff=True)
        self.member=User.objects.create_user('price-member')
        PoolSettings.objects.create(pk=1,owner=self.owner)
        self.provider=Provider.objects.create(name='智谱',base_url='https://open.bigmodel.cn/api/paas/v4')
        self.model=PoolModel.objects.create(provider=self.provider,model_id='glm-5.3-flash')
        self.client.force_login(self.owner)
    def tearDown(self): cache.clear()
    def update(self,model=None):
        return self.client.post(reverse('api_model_price'),json.dumps({'id':(model or self.model).pk,'action':'automatic'}),content_type='application/json')
    def existing(self):
        return PriceVersion.objects.create(model=self.model,effective_from=timezone.now(),input_rate=9,output_rate=10,cached_rate=9,cache_write_rate=9)

    @patch('aihub.vendor_prices.text_request',return_value=GLM)
    def test_auto_price_saves_cache_rates_and_daily_record(self,read):
        response=self.update();self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['input_rate'],'0.800000')
        self.assertEqual(self.model.prices.first().cached_rate,Decimal('.23'))
        self.assertEqual(DailyPrice.objects.get(model=self.model).status,'verified')

    @patch('aihub.vendor_prices.text_request',side_effect=RuntimeError('test-secret-should-never-leak'))
    def test_failure_preserves_previous_price_and_hides_upstream_details(self,read):
        old=self.existing();response=self.update()
        self.assertEqual(response.status_code,400);self.assertEqual(self.model.prices.first().pk,old.pk)
        self.assertNotIn('test-secret',response.content.decode());self.assertIn('已有价格',response.json()['error'])

    @patch('aihub.vendor_prices.text_request',return_value=GLM)
    def test_unknown_model_does_not_become_free(self,read):
        self.model.model_id='glm-new-unknown';self.model.save()
        self.assertEqual(self.update().status_code,400);self.assertFalse(self.model.prices.exists())

    @patch('aihub.vendor_prices.text_request')
    def test_manual_price_not_overwritten_by_sync(self,read):
        old=self.existing();refresh_prices(force=True)
        self.assertEqual(self.model.prices.first().pk,old.pk);read.assert_not_called()

    @patch('aihub.vendor_prices.text_request',return_value=GLM)
    def test_batch_uses_one_cached_fetch_and_skips_disabled_models(self,read):
        PoolModel.objects.create(provider=self.provider,model_id='glm-5.3-flashx')
        paused=PoolModel.objects.create(provider=self.provider,model_id='glm-5.1',enabled=False)
        self.assertEqual(refresh_prices(force=True),2);read.assert_called_once()
        self.assertFalse(paused.prices.exists());self.assertEqual(DailyPrice.objects.count(),2)

    @patch('aihub.vendor_prices.text_request')
    def test_management_open_does_not_fetch_and_unsupported_button_disabled(self,read):
        unknown=Provider.objects.create(name='自定义',base_url='https://example.com/v1')
        PoolModel.objects.create(provider=unknown,model_id='custom-model')
        response=self.client.get(reverse('api_manage'))
        self.assertContains(response,'这个连接尚未接入可靠的自动价格来源')
        self.assertContains(response,'data-unsupported="true" disabled')
        read.assert_not_called()

    @patch('aihub.vendor_prices.text_request')
    def test_member_cannot_fetch_or_update_prices(self,read):
        self.client.force_login(self.member)
        self.assertEqual(self.update().status_code,403);read.assert_not_called()

    @patch('aihub.vendor_prices.text_request')
    def test_manage_has_three_official_sources_and_unsupported_explanation(self,read):
        for name,url,model in [('百炼','https://dashscope.aliyuncs.com/compatible-mode/v1','qwen3.8-flash'),
                               ('MiniMax','https://api.minimaxi.com/v1','MiniMax-M2.7'),
                               ('自定义','https://example.com/v1','custom-model')]:
            provider=Provider.objects.create(name=name,base_url=url)
            PoolModel.objects.create(provider=provider,model_id=model)
        response=self.client.get(reverse('api_manage'),{'prices':'1'})
        self.assertContains(response,'读取智谱官方按量价')
        self.assertContains(response,'读取 MiniMax 官方按量价')
        self.assertContains(response,'读取百炼北京地域')
        read.assert_not_called()
        target=os.environ.get('WORKBENCH_CAPTURE_UI')
        if target:
            path=Path(target)/'vendor-prices.html';path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(response.content)

    @patch('aihub.vendor_prices.text_request',return_value=GLM)
    @patch('aihub.discovery.json_request',return_value={'data':[{'id':'glm-5.3-flash'}]})
    @patch('aihub.views.store_key')
    def test_discovery_enable_uses_price_without_returning_key(self,store,models,price):
        root=Path(settings.BASE_DIR)/'.test-scratch';root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as directory,override_settings(DATA_DIR=Path(directory)):
            response=self.client.post(reverse('api_discover'),json.dumps({'id':self.provider.pk,'base_url':self.provider.base_url,'api_key':'fake-test-key'}),content_type='application/json')
            self.assertEqual(response.status_code,200);proposal=response.json()
            self.assertNotIn('fake-test-key',response.content.decode())
            self.assertEqual(proposal['models'][0]['price']['input_rate'],'0.8')
            saved=self.client.post(reverse('api_enable_models'),json.dumps({'ticket':proposal['ticket'],'models':['glm-5.3-flash']}),content_type='application/json')
            self.assertEqual(saved.status_code,200);self.assertEqual(saved.json()['missing_prices'],[])
            self.assertEqual(self.model.prices.first().cached_rate,Decimal('.23'))
