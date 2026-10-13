import json
from django.contrib.auth.models import User
from django.test import TestCase,Client
from django.urls import reverse
from django.core.exceptions import PermissionDenied,ValidationError
from .tool_registry import registry,Plugin,Tool
from .plugins import catalog,set_enabled
from .models import AgentPluginSetting
from . import test_delegation as fixtures


class PluginMarketplaceTests(TestCase):
    def setUp(self):
        self.user=User.objects.create_user('plugin-user')
        self.other=User.objects.create_user('other-plugin-user')
        self.client.force_login(self.user)

    def change(self,plugin='tasks',data=None):
        return self.client.post(reverse('plugin_setting',args=[plugin]),json.dumps(data if data is not None else {'enabled':False}),content_type='application/json')

    def test_every_builtin_is_in_catalog_and_marketplace(self):
        response=self.client.get(reverse('plugin_marketplace'))
        self.assertEqual(response.status_code,200)
        self.assertEqual({p['id'] for p in response.context['market_plugins']},set(registry.plugins))
        for plugin in registry.plugins.values():
            self.assertContains(response,plugin.description)
            self.assertContains(response,reverse('plugin_detail',args=[plugin.id]))
        self.assertContains(response,'aihub/plugins.js')
        self.assertContains(response,'aihub/plugins.css')
        self.assertContains(response,'data-plugin-toggle',count=len(registry.plugins))
        self.assertNotContains(response,'aihub/usage.js')
        self.assertNotContains(response,'type="file"')

    def test_details_show_actual_tools_and_configuration(self):
        response=self.client.get(reverse('plugin_detail',args=['tasks']))
        self.assertContains(response,'创建任务');self.assertContains(response,'更新任务进度')
        self.assertContains(response,'?authorize=tasks')
        self.assertContains(response,'停用后不会开始新的插件操作')

    def test_enabled_filter_and_search_include_tool_labels(self):
        set_enabled(self.user,'web',False)
        response=self.client.get(reverse('plugin_marketplace'),{'view':'enabled','q':'互联网'})
        self.assertEqual(response.context['plugins'],[])
        response=self.client.get(reverse('plugin_marketplace'),{'q':'创建任务'})
        self.assertEqual([p['id'] for p in response.context['plugins']],['tasks'])

    def test_existing_preferences_are_preserved(self):
        AgentPluginSetting.objects.create(user=self.user,plugin='workspace',enabled=False)
        response=self.client.get(reverse('plugin_marketplace'))
        self.assertFalse(next(p for p in response.context['market_plugins'] if p['id']=='workspace')['enabled'])

    def test_state_refresh_uses_current_preferences_and_requires_login(self):
        set_enabled(self.user,'web',False)
        response=self.client.get(reverse('plugin_state'))
        self.assertEqual(response.status_code,200)
        self.assertFalse(next(row for row in response.json()['plugins'] if row['id']=='web')['enabled'])
        self.assertIn('no-store',response.headers['Cache-Control'])
        self.client.logout();self.assertEqual(self.client.get(reverse('plugin_state')).status_code,401)

    def test_changes_are_personal_and_idempotent(self):
        for _ in range(2):self.assertEqual(self.change().status_code,200)
        self.assertEqual(AgentPluginSetting.objects.filter(user=self.user,plugin='tasks').count(),1)
        self.assertFalse(next(p for p in catalog(self.user) if p['id']=='tasks')['enabled'])
        self.assertTrue(next(p for p in catalog(self.other) if p['id']=='tasks')['enabled'])
        self.assertTrue(self.change(data={'enabled':True}).json()['plugin']['enabled'])

    def test_unknown_plugins_and_arbitrary_configuration_are_rejected(self):
        for plugin,data in [('missing',{'enabled':False}),('tasks',{'enabled':'false'}),('tasks',{'enabled':True,'user_id':self.other.pk}),('tasks',{'enabled':True,'handler':'os.system'})]:
            self.assertEqual(self.change(plugin,data).status_code,400)
        self.assertFalse(AgentPluginSetting.objects.exists())
        self.assertEqual(self.client.get(reverse('plugin_detail',args=['missing'])).status_code,404)

    def test_settings_require_login_post_and_csrf(self):
        self.assertEqual(self.client.get(reverse('plugin_setting',args=['tasks'])).status_code,405)
        self.client.logout()
        self.assertEqual(self.change().status_code,401)
        client=Client(enforce_csrf_checks=True);client.force_login(self.user)
        self.assertEqual(client.post(reverse('plugin_setting',args=['tasks']),json.dumps({'enabled':False}),content_type='application/json').status_code,403)

    def test_catalog_automatically_includes_new_trusted_registrations(self):
        plugin=Plugin('synthetic-test','测试插件',(Tool('synthetic-read','测试读取','测试',{},()),),description='合成插件')
        registry.register(plugin)
        try:
            self.assertIn(plugin.id,[p['id'] for p in catalog(self.user)])
            self.assertContains(self.client.get(reverse('plugin_marketplace')),plugin.label)
        finally:
            registry.plugins.pop(plugin.id);registry.tools.pop('synthetic-read');registry.owners.pop('synthetic-read')

    def test_sensitive_configuration_is_not_exposed(self):
        response=self.client.get(reverse('plugin_marketplace'))
        self.assertNotContains(response,'api-pool-keys.json')
        self.assertIn('no-store',response.headers['Cache-Control'])


class MarketplaceDelegationTests(TestCase):
    def setUp(self):fixtures.DelegationTests.setUp(self)
    def execute(self,*args,**kwargs):return fixtures.DelegationTests.execute(self,*args,**kwargs)
    def test_marketplace_disable_blocks_existing_authorization(self):
        self.client.force_login(self.user)
        result=self.client.post(reverse('plugin_setting',args=['tasks']),json.dumps({'enabled':False}),content_type='application/json')
        self.assertEqual(result.status_code,200)
        with self.assertRaises(PermissionDenied):self.execute()
        self.assertTrue(self.grant.actions)

    def test_legacy_assistant_setting_and_marketplace_share_storage(self):
        self.client.force_login(self.user)
        result=self.client.post(reverse('ai_capabilities'),json.dumps({'action':'plugin','plugin':'tasks','enabled':False}),content_type='application/json')
        self.assertEqual(result.status_code,200)
        page=self.client.get(reverse('plugin_detail',args=['tasks']))
        self.assertFalse(page.context['plugin']['enabled'])
