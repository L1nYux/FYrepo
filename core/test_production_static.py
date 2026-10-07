"""Exercise the storage used on the server, independently of test/debug defaults."""
import io
import json
import tempfile
from pathlib import Path
from django.conf import settings
from django.core.management import call_command
from django.test import SimpleTestCase, override_settings


class ProductionStaticTests(SimpleTestCase):
    def test_complete_manifest_and_local_emoji_assets(self):
        parent=Path(settings.BASE_DIR)/'.test-scratch'
        parent.mkdir(exist_ok=True)
        storages=dict(settings.STORAGES)
        storages['staticfiles']={'BACKEND':'whitenoise.storage.CompressedManifestStaticFilesStorage'}
        with tempfile.TemporaryDirectory(prefix='production-static-',dir=parent) as target:
            folder=Path(target)
            self.assertTrue(folder.resolve().is_relative_to(parent.resolve()))
            with override_settings(DEBUG=False,STATIC_ROOT=target,STORAGES=storages):
                call_command('collectstatic',interactive=False,verbosity=0,stdout=io.StringIO(),stderr=io.StringIO())
                manifest=json.loads((folder/'staticfiles.json').read_text(encoding='utf-8'))
                for name in ('browser.js','data.json','zh.json'):
                    mapped=manifest['paths']['vendor/emoji-mart/'+name]
                    self.assertNotEqual(mapped,'vendor/emoji-mart/'+name)
                    self.assertTrue((folder/mapped).is_file(),mapped)
                script=(folder/manifest['paths']['vendor/emoji-mart/browser.js']).read_text(encoding='utf-8')
                self.assertIn('window.EmojiMart',script)
                self.assertNotIn('sourceMappingURL=browser.js.map',script)
                self.assertTrue(Path(str(folder/manifest['paths']['vendor/emoji-mart/browser.js'])+'.gz').is_file())
