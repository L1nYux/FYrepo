from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from django.conf import settings
from django.test import SimpleTestCase
from django.template import Context, Template
from .frontend_assets import BUNDLES, Bundle, page_features, scripts_for


class FrontendAssets(SimpleTestCase):
    def assets(self, name, **flags):
        context = {'request': SimpleNamespace(resolver_match=SimpleNamespace(url_name=name)), **flags}
        return scripts_for(page_features(context))

    def test_public_pages_load_only_base(self):
        self.assertEqual(self.assets('public_home'), scripts_for(['base']))
        self.assertNotIn('vendor/emoji-mart/browser.js', self.assets('public_home'))

    def test_work_lists_share_components_without_chat_or_assistant_dependencies(self):
        for name in ('dashboard','task_list'):
            assets=self.assets(name,shell_enabled=True)
            self.assertEqual(assets.count('core/work-list.js'),1)
            self.assertNotIn('core/chat-references.js',assets)
            self.assertNotIn('vendor/emoji-mart/browser.js',assets)
        self.assertNotIn('core/work-list.js',self.assets('project_detail',shell_enabled=True))

    def test_recruitment_does_not_load_conversation_and_ai_features(self):
        assets = self.assets('messages_team_recruitment', shell_enabled=True, communication_management=True)
        self.assertNotIn('core/chat-references.js', assets)
        self.assertNotIn('vendor/emoji-mart/browser.js', assets)
        self.assertNotIn('aihub/web-browser.js', assets)
        self.assertNotIn('aihub/usage.js', assets)
        self.assertIn('aihub/account-usage.js', assets)

    def test_chat_features_have_ordered_dependencies(self):
        assets = self.assets('personal_chat', shell_enabled=True, is_messages=True)
        self.assertLess(assets.index('core/app-runtime.js'), assets.index('core/app-experience.js'))
        self.assertLess(assets.index('core/emoji.js'), assets.index('core/chat-stickers.js'))
        self.assertLess(assets.index('core/app-experience.js'), assets.index('core/conversation-workflows.js'))

    def test_task_keeps_comments_but_does_not_open_local_chat_database(self):
        assets = self.assets('task_detail', shell_enabled=True)
        self.assertIn('core/comment-emoji.js', assets)
        self.assertIn('core/mobile-workflows.js', assets)
        self.assertNotIn('core/local-chat.js', assets)

    def test_assistant_keeps_emoji_browser_and_usage(self):
        assets = self.assets('ai_assistant', shell_enabled=True, is_assistant=True, is_ai_module=True)
        self.assertIn('core/emoji.js', assets)
        self.assertIn('aihub/web-browser.js', assets)
        self.assertIn('aihub/activity-scale.js', assets)
        self.assertNotIn('core/chat-references.js', assets)

    def test_all_bundles_exist_and_deduplicate(self):
        assets = scripts_for(BUNDLES)
        self.assertEqual(len(assets), len(set(assets)))
        for asset in assets:
            self.assertTrue((Path(settings.BASE_DIR) / 'static' / asset).is_file(), asset)

    def test_invalid_dependency_fails_explicitly(self):
        with self.assertRaises(KeyError): scripts_for(['missing'])

    def test_dependency_cycles_fail_explicitly(self):
        with patch.dict(BUNDLES, {'cycle': Bundle(requires=('cycle',))}):
            with self.assertRaises(ValueError): scripts_for(['cycle'])

    def test_template_escapes_and_renders_each_script_once(self):
        html = Template('{% load frontend_assets %}{% app_assets %}').render(Context({'shell_enabled':False}))
        self.assertEqual(html.count('<script '), len(scripts_for(['base'])))
        self.assertIn('app-runtime.js', html)

    def test_every_comment_detail_has_emoji(self):
        for name in ('project_detail', 'task_detail', 'document_detail'):
            self.assertIn('core/comment-emoji.js', self.assets(name, shell_enabled=True))

    def test_failed_post_keeps_the_renderers_features(self):
        assets = self.assets('task_progress', shell_enabled=True, frontend_features=('task',))
        self.assertIn('core/mobile-workflows.js', assets)
        self.assertIn('core/comment-emoji.js', assets)
        self.assertEqual(assets.count('core/mobile-workflows.js'), 1)

    def test_explicit_and_route_features_are_deduplicated(self):
        assets = self.assets('task_detail', shell_enabled=True, frontend_features=('task',))
        self.assertEqual(assets.count('core/mobile-workflows.js'), 1)
