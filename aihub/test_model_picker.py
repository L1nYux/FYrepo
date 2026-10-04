import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase, SimpleTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from .discovery import fetch_models
from .model_catalog import describe
from .models import Provider, PoolModel, PoolSettings, PriceVersion


class CatalogClassificationTests(SimpleTestCase):
    def test_known_families_and_uses(self):
        for identifier,vendor,use,supported in [
            ('qwen-image-2.1-pro','千问','image',False),
            ('stepfun/step-5-preview','阶跃星辰','chat',True),
            ('glm-5.3-prime','智谱','chat',True),
            ('ZHIPU/GLM-5.3-FlashX','智谱','vision',True),
            ('qwen3-vl-plus','千问','vision',True),
            ('wan-2.2-t2v','通义万相','video',False),
            ('qwen3-tts-flash','千问','audio',False),
            ('text-embedding-v4','其他 / 未标明','embedding',False),
        ]:
            with self.subTest(identifier=identifier):
                value=describe(identifier)
                self.assertEqual((value['vendor'],value['use'],value['assistant_supported']),(vendor,use,supported))

    def test_metadata_identifies_unknown_image_and_vision_models(self):
        self.assertFalse(describe('unfamiliar',{'architecture':{'output_modalities':['image']}})['assistant_supported'])
        self.assertEqual(describe('unfamiliar',{'owned_by':'New vendor','architecture':{'output_modalities':['text'],'input_modalities':['image','text']}})['use'],'vision')
        self.assertTrue(describe('custom-model')['assistant_supported'])

    @patch('aihub.discovery.json_request')
    def test_discovery_retains_nonchat_models_with_explicit_support_flag(self,read):
        read.return_value={'data':[{'id':'qwen-plus'},{'id':'qwen-image-2.1-pro'},{'id':'text-embedding-v4'}]}
        rows,truncated=fetch_models(SimpleNamespace(protocol='openai',base_url='https://dashscope.aliyuncs.com/compatible-mode/v1'),'fake')
        self.assertEqual(len(rows),3);self.assertFalse(truncated)
        self.assertEqual([row['assistant_supported'] for row in rows],[True,False,False])


class ModelPickerManagementTests(TestCase):
    def setUp(self):
        self.owner=User.objects.create_user('picker-owner',is_staff=True)
        PoolSettings.objects.create(pk=1,owner=self.owner)
        self.client.force_login(self.owner)
        self.provider=Provider.objects.create(name='百炼',base_url='https://dashscope.aliyuncs.com/compatible-mode/v1')
        self.paused_provider=Provider.objects.create(name='停用连接',base_url='https://example.com/v1',enabled=False)
        self.missing=PoolModel.objects.create(provider=self.provider,model_id='qwen-missing')
        self.priced=PoolModel.objects.create(provider=self.provider,model_id='qwen-priced')
        self.paused=PoolModel.objects.create(provider=self.provider,model_id='qwen-paused',enabled=False)
        self.paused_connection_model=PoolModel.objects.create(provider=self.paused_provider,model_id='paused-connection-model')
        for model in (self.priced,self.paused):
            PriceVersion.objects.create(model=model,effective_from=timezone.now(),input_rate=1,output_rate=2,cached_rate=1,cache_write_rate=0)

    def test_price_page_only_has_active_models_with_missing_first(self):
        response=self.client.get(reverse('api_manage'),{'prices':'1'})
        self.assertEqual([m.pk for m in response.context['models']],[self.missing.pk,self.priced.pk])
        self.assertEqual(response.context['missing_price_count'],1)
        self.assertNotContains(response,f'id="pool-price-{self.paused.pk}"')
        self.assertNotContains(response,f'id="pool-price-{self.paused_connection_model.pk}"')
        self.assertContains(response,'qwen-paused')  # separate management keeps the record
        if os.environ.get('WORKBENCH_CAPTURE_UI'):
            path=Path(settings.BASE_DIR)/'.test-scratch'/'render-pages'/'model-picker.html'
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(response.content)

    def test_disabled_advanced_price_link_returns_to_model_management(self):
        for model in (self.paused,self.paused_connection_model):
            response=self.client.get(reverse('api_manage'),{'model':model.pk})
            self.assertRedirects(response,reverse('api_manage')+'#pool-model-management',fetch_redirect_response=False)

    def test_disable_reenable_preserves_existing_price(self):
        price_id=self.priced.prices.first().pk
        self.client.post(reverse('api_manage'),{'action':'toggle_model','id':self.priced.pk})
        self.assertNotContains(self.client.get(reverse('api_manage')),f'id="pool-price-{self.priced.pk}"')
        self.client.post(reverse('api_manage'),{'action':'toggle_model','id':self.priced.pk})
        response=self.client.get(reverse('api_manage'))
        self.assertContains(response,f'id="pool-price-{self.priced.pk}"')
        self.assertEqual(self.priced.prices.first().pk,price_id)

    def test_discovery_and_save_only_persist_checked_supported_models(self):
        root=Path(settings.BASE_DIR)/'.test-scratch';root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as data_dir, override_settings(DATA_DIR=Path(data_dir)), \
             patch('aihub.discovery.json_request',return_value={'data':[{'id':'qwen-missing'},{'id':'qwen-priced'},{'id':'qwen-image-2.1-pro'}]}), \
             patch('aihub.vendor_prices.official_prices',return_value={}), \
             patch('aihub.views.provider_key',return_value='fake'),patch('aihub.views.store_key'):
            proposal=self.client.post(reverse('api_discover'),json.dumps({'id':self.provider.pk,'base_url':self.provider.base_url}),content_type='application/json').json()
            self.assertEqual(proposal['channel'],'阿里云百炼')
            invalid=self.client.post(reverse('api_enable_models'),json.dumps({'ticket':proposal['ticket'],'models':['qwen-image-2.1-pro']}),content_type='application/json')
            self.assertEqual(invalid.status_code,400);self.assertFalse(PoolModel.objects.filter(model_id='qwen-image-2.1-pro').exists())
            valid=self.client.post(reverse('api_enable_models'),json.dumps({'ticket':proposal['ticket'],'models':['qwen-missing']}),content_type='application/json')
            self.assertEqual(valid.status_code,200)
            self.priced.refresh_from_db();self.assertFalse(self.priced.enabled)
            self.assertEqual(PriceVersion.objects.filter(model=self.priced).count(),1)
            self.assertEqual([m.pk for m in self.client.get(reverse('api_manage')).context['models']],[self.missing.pk])
