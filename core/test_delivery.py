"""Development bundles must not advertise an unpublished automatic update."""
import contextlib
import io
import json
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch
from django.test import SimpleTestCase
from tools import build_delivery


class DeliveryTests(SimpleTestCase):
    def exercise(self,development):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); (root/'desktop').mkdir(); (root/'docs').mkdir()
            (root/'desktop/package.json').write_text('{"version":"0.2.19"}',encoding='utf-8')
            (root/'docs/DESKTOP_RELEASE_NOTES.md').write_text('[复查](REVIEW_0_2_19.md)',encoding='utf-8')
            (root/'docs/REVIEW_0_2_19.md').write_text('复查记录',encoding='utf-8')
            assets=root/'assets';assets.mkdir();output=root/'output'
            for suffix in ['win-x64.exe','mac-arm64.dmg','mac-x64.dmg']:
                (assets/('ResearchWorkbench-0.2.19-'+suffix)).write_bytes(b'x'*(1024*1024+1))
            with patch.object(build_delivery,'ROOT',root),contextlib.redirect_stdout(io.StringIO()):
                build_delivery.build(assets,output,'1'*40,development)
            folder=output/'知域-0.2.19-安装包'
            information=json.loads((folder/'构建信息.json').read_text(encoding='utf-8'))
            self.assertEqual(information['development'],development)
            with zipfile.ZipFile(output/'知域-0.2.19-Windows-Mac-群发包.zip') as bundle:
                self.assertIsNone(bundle.testzip())
                names={Path(name).name for name in bundle.namelist()}
                self.assertIn('REVIEW_0_2_19.md',names)
                self.assertIn('0.2.19-服务器更新.txt',names)
                text=bundle.read(folder.name+'/安装与自动更新.txt').decode('utf-8')
                self.assertNotIn('../',text)
                if development:
                    self.assertIn('尚未发布为正式自动更新',text)
                    self.assertIn('同版本',text)
                else:
                    self.assertIn('点击头像旁的更新按钮',text)

    def test_development_bundle_contains_review_and_manual_update_instructions(self):
        self.exercise(True)

    def test_release_bundle_retains_normal_update_instructions(self):
        self.exercise(False)
