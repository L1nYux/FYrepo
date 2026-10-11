"""Browser profile regressions; isolated files, no institution login or CNKI data."""
import asyncio
import importlib.util
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import AsyncMock, patch

from django.conf import settings
from django.test import SimpleTestCase

ENGINE = settings.BASE_DIR / "vendor/sample_llm"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))
from integrations import browser_profile, cnki_external


class BrowserProfileTests(SimpleTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fyrepo-profile-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source, self.destination = self.root / "master", self.root / "worker"
        self.auth_files = {
            "Local State": b"encrypted-key-test-fixture",
            "Default/Network/Cookies": b"cookie-test-fixture",
            "Default/Network/Cookies-wal": b"cookie-wal-test-fixture",
            "Default/Preferences": b"preferences-test-fixture",
            "Default/Secure Preferences": b"secure-preferences-test-fixture",
            "Default/Local Storage/leveldb/000003.log": b"local-storage-test-fixture",
            "Default/IndexedDB/cnki.indexeddb.leveldb/000003.log": b"indexed-db-test-fixture",
            "Default/Session Storage/000003.log": b"session-storage-test-fixture",
        }
        self.cache_files = [
            "EdgeOptimizationGuideModels/2026.9.18.5/variants/webgpu-fp16-prerelease/configs/proofreader_api.binarypb",
            "EdgeOptimizationGuideModelsManifest/2026.9.18.5/variants/webgpu-fp32-prerelease/configs/summarizer_api.binarypb",
            "Default/Code Cache/js/unused", "Default/GPUCache/unused",
            "Default/Service Worker/CacheStorage/unused", "SingletonLock",
            "Default/Local Storage/leveldb/LOCK",
        ]
        for rel, payload in {**self.auth_files, **dict.fromkeys(self.cache_files, b"disposable")}.items():
            file = self.source / rel
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(payload)

    def assert_auth_preserved(self, destination):
        for rel, payload in self.auth_files.items():
            self.assertEqual((destination / rel).read_bytes(), payload, rel)
            self.assertEqual((self.source / rel).read_bytes(), payload, rel)
        for rel in self.cache_files:
            self.assertFalse((destination / rel).exists(), rel)
            self.assertTrue((self.source / rel).exists(), rel)

    def test_authentication_state_preserved_and_caches_excluded(self):
        browser_profile.clone_browser_profile(self.source, self.destination)
        self.assert_auth_preserved(self.destination)

    def test_old_copy_reproduces_winerror3_and_filtered_copy_succeeds(self):
        actual_copy = shutil.copy2

        def windows_copy(source, destination, **kwargs):
            if "EdgeOptimizationGuideModels" in str(source):
                raise FileNotFoundError("[WinError 3] 系统找不到指定的路径。")
            return actual_copy(source, destination, **kwargs)

        with self.assertRaisesRegex(shutil.Error, "WinError 3"):
            shutil.copytree(self.source, self.root / "old-unfiltered", copy_function=windows_copy)
        with patch.object(browser_profile.shutil, "copy2", side_effect=windows_copy):
            browser_profile.clone_browser_profile(self.source, self.destination)
        self.assert_auth_preserved(self.destination)

    def test_login_file_failure_stops_and_removes_partial_profile(self):
        actual_copy = shutil.copy2

        def locked_cookie(source, destination, **kwargs):
            if Path(source).name == "Cookies":
                raise PermissionError("[WinError 32] Cookies 正在使用")
            return actual_copy(source, destination, **kwargs)

        with patch.object(browser_profile.shutil, "copy2", side_effect=locked_cookie):
            with self.assertRaisesRegex(RuntimeError, "登录资料复制失败.*WinError 32") as caught:
                browser_profile.clone_browser_profile(self.source, self.destination)
        self.assertLess(len(str(caught.exception)), 400)
        self.assertFalse(self.destination.exists())
        self.assertEqual((self.source / "Default/Network/Cookies").read_bytes(), self.auth_files["Default/Network/Cookies"])

    def test_previous_worker_profile_is_replaced_without_touching_master(self):
        self.destination.mkdir()
        (self.destination / "stale-login").write_text("old", encoding="utf-8")
        browser_profile.clone_browser_profile(self.source, self.destination)
        self.assertFalse((self.destination / "stale-login").exists())
        self.assert_auth_preserved(self.destination)

    def test_invalid_destination_cannot_delete_source(self):
        for destination in (self.source, self.source.parent, self.source / "nested"):
            with self.subTest(destination=destination):
                with self.assertRaisesRegex(RuntimeError, "不能相同或相互包含"):
                    browser_profile.clone_browser_profile(self.source, destination)
                self.assertTrue((self.source / "Local State").exists())

    def test_windows_extended_local_and_unc_paths(self):
        local = r"C:\Users\cxy\Desktop\FYrepo\Default\Network\Cookies"
        unc = r"\\server\share\FYrepo\Default\Network\Cookies"
        extended = r"\\?\C:\FYrepo\Default\Network\Cookies"
        self.assertEqual(browser_profile._extended_path(local, windows=True), "\\\\?\\" + local)
        self.assertEqual(browser_profile._extended_path(unc, windows=True), "\\\\?\\UNC\\" + unc[2:])
        self.assertEqual(browser_profile._extended_path(extended, windows=True), extended)
        self.assertEqual(browser_profile._extended_path(local, windows=False), local)

    def test_collection_clones_login_state_through_shared_helper(self):
        with patch.object(cnki_external, "MASTER_PROFILE", self.source):
            cnki_external._clone_login_profile(self.destination)
        self.assert_auth_preserved(self.destination)

    @skipUnless(importlib.util.find_spec("playwright"), "PDF 下载入口实测需先安装 tools/cnki_agent/requirements.txt")
    def test_pdf_download_uses_the_same_filtered_profile(self):
        # Keep the optional Agent import inside the guarded test: Web-only
        # installations must still discover and run the other profile tests.
        from integrations import pdf_downloader

        context = SimpleNamespace(pages=[object()], close=AsyncMock())
        playwright = SimpleNamespace(stop=AsyncMock())
        with (patch.object(pdf_downloader, "MASTER_PROFILE", self.source),
              patch.object(pdf_downloader, "ROOT", self.root),
              patch.object(pdf_downloader, "_launch_context", AsyncMock(return_value=(playwright, context))) as launch):
            self.assertEqual(asyncio.run(pdf_downloader.download_selected_async([], self.root / "pdfs")), [])
        profile = self.root / "runtime_outputs/pdf_download_profile"
        self.assert_auth_preserved(profile)
        launch.assert_awaited_once_with(profile)
        context.close.assert_awaited_once()
        playwright.stop.assert_awaited_once()
