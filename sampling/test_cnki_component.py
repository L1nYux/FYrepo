"""H1 regression: genuine archives, corrupt archives, and real offline pip installation."""
import importlib.util
import json
import os
import shutil
import struct
import subprocess
import sys
import sysconfig
import tempfile
import venv
import zipfile
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase

ENGINE = settings.BASE_DIR / "vendor/sample_llm"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))
from integrations import cnki_external as cnki
from integrations.component_integrity import (ARCHIVE_NAME, WHEEL_NAME, SOURCE_PREFIX,
                                              ComponentIntegrityError, validate_bundled_component)


class CnkiArchiveIntegrityTests(SimpleTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "vendor/sample_llm"
        shutil.copytree(ENGINE, self.root, ignore=shutil.ignore_patterns("__pycache__", "runtime_outputs"))
        shutil.copyfile(ENGINE.parent / "SAMPLE_LLM_SOURCE.json", self.root.parent / "SAMPLE_LLM_SOURCE.json")

    def rehash(self, name):
        import hashlib
        manifest_path = self.root.parent / "SAMPLE_LLM_SOURCE.json"
        manifest = json.loads(manifest_path.read_text())
        for entry in manifest["files"]:
            if entry["path"] == name:
                entry["sha256"] = hashlib.sha256((self.root / name).read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    def rewrite(self, name, member, content):
        path = self.root / name
        with zipfile.ZipFile(path) as source:
            files = {item.filename: source.read(item) for item in source.infolist()}
        files[member] = content
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as target:
            for filename, data in files.items():
                target.writestr(filename, data)
        self.rehash(name)

    def test_delivered_archives_and_active_source_manifest_pass(self):
        result = validate_bundled_component(self.root)
        self.assertEqual(result["version"], "0.2.0")
        self.assertEqual(result["checked_files"], 22)
        self.assertEqual(len(result["module_sha256"]), 6)

    def test_missing_manifest_is_reported_as_business_error(self):
        (self.root.parent / "SAMPLE_LLM_SOURCE.json").unlink()
        with self.assertRaisesRegex(ComponentIntegrityError, "来源清单无法读取"):
            validate_bundled_component(self.root)

    def test_changed_wheel_without_manifest_update_is_rejected(self):
        file = self.root / "third_party" / WHEEL_NAME
        file.write_bytes(file.read_bytes() + b"changed")
        with self.assertRaisesRegex(ComponentIntegrityError, "SHA256 不匹配"):
            validate_bundled_component(self.root)

    def test_matching_hash_does_not_allow_archive_without_eocd(self):
        for name in (ARCHIVE_NAME, WHEEL_NAME):
            with self.subTest(name=name):
                path = "third_party/" + name
                file = self.root / path
                original = file.read_bytes()
                file.write_bytes(original[:original.rfind(b"PK\x05\x06")])
                self.rehash(path)
                with self.assertRaisesRegex(ComponentIntegrityError, "BadZipFile"):
                    validate_bundled_component(self.root)
                file.write_bytes(original)
                self.rehash(path)

    def test_matching_hash_does_not_allow_corrupt_compressed_entry(self):
        path = "third_party/" + WHEEL_NAME
        file = self.root / path
        raw = bytearray(file.read_bytes())
        # Damage the first compressed payload, leaving directory/EOCD and the manifest consistent.
        nlen, elen = struct.unpack_from("<HH", raw, 26)
        raw[30 + nlen + elen + 3] ^= 0x80
        file.write_bytes(raw)
        self.rehash(path)
        with self.assertRaises(ComponentIntegrityError):
            validate_bundled_component(self.root)

    def test_valid_zip_with_stale_wheel_record_is_rejected(self):
        self.rewrite("third_party/" + WHEEL_NAME, "cnki_metadata_exporter/exporter.py", b"changed but valid ZIP")
        with self.assertRaisesRegex(ComponentIntegrityError, "RECORD 中的"):
            validate_bundled_component(self.root)

    def test_wheel_and_source_must_contain_identical_real_modules(self):
        self.rewrite("third_party/" + ARCHIVE_NAME,
                     SOURCE_PREFIX + "src/cnki_metadata_exporter/exporter.py", b"changed source")
        with self.assertRaisesRegex(ComponentIntegrityError, "固定源码快照不一致"):
            validate_bundled_component(self.root)

    def test_installer_never_starts_pip_for_corrupt_bundle(self):
        file = self.root / "third_party" / WHEEL_NAME
        file.write_bytes(b"PK\x03\x04")
        self.rehash("third_party/" + WHEEL_NAME)
        with patch.object(cnki, "ROOT", self.root), patch.object(cnki, "_stream") as stream:
            with self.assertRaises(ComponentIntegrityError):
                list(cnki.install_package())
            stream.assert_not_called()

    def test_status_reports_invalid_bundle_without_raising(self):
        (self.root.parent / "SAMPLE_LLM_SOURCE.json").unlink()
        with patch.object(cnki, "ROOT", self.root), patch.object(cnki, "_playwright_browser_ready", return_value=False):
            result = cnki.package_status()
        self.assertFalse(result["integrity_ok"])
        self.assertFalse(result["installed"])
        self.assertIn("完整性校验失败", result["integrity_error"])


class CnkiOfflineInstallationTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.temp = tempfile.TemporaryDirectory(prefix="fyrepo-cnki-install-test-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.environment = Path(cls.temp.name) / "venv"
        # Inherit already-installed Python dependencies; exporter itself is installed locally by pip.
        venv.EnvBuilder(with_pip=True).create(cls.environment)
        cls.python = cls.environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        # A nested venv's --system-site-packages points at the base interpreter, not
        # the project's venv. Append the active dependency directory after this
        # clean venv's own site-packages, so its installed exporter wins resolution.
        site = Path(cls.run_python("-c", "import sysconfig; print(sysconfig.get_path('purelib'))").strip())
        (site / "fyrepo_test_dependencies.pth").write_text(sysconfig.get_path("purelib") + "\n", encoding="utf-8")
        cls.run_python("-m", "pip", "install", "--no-index", "--no-deps", "--force-reinstall",
                       "--disable-pip-version-check", str(ENGINE / "third_party" / WHEEL_NAME))

    @classmethod
    def run_python(cls, *args):
        result = subprocess.run([str(cls.python), *args], cwd=settings.BASE_DIR,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", timeout=60, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        if result.returncode:
            raise AssertionError(result.stdout)
        return result.stdout

    def test_real_offline_pip_installs_in_isolated_environment(self):
        output = self.run_python("-c", "import sys, cnki_metadata_exporter; "
                                 "import cnki_metadata_exporter.queries, cnki_metadata_exporter.merge_metadata; "
                                 "print(cnki_metadata_exporter.__version__); print(cnki_metadata_exporter.__file__)")
        self.assertIn("0.2.0", output)
        self.assertIn(str(self.environment), output)
        self.assertIn("--include-database", self.run_python("-m", "cnki_metadata_exporter.merge_metadata", "--help"))

    @skipUnless(importlib.util.find_spec("playwright"), "采集入口实测需先安装 tools/cnki_agent/requirements.txt")
    def test_real_agent_installer_and_collector_entry_point(self):
        output = self.run_python(str(settings.BASE_DIR / "tools/verify_cnki_component.py"), "--install")
        self.assertIn("OFFLINE_INSTALL_OK", output)
        self.assertIn("--batch-size", self.run_python(str(ENGINE / "integrations/collector_runner.py"), "--help"))
        self.assertIn("--profile", self.run_python(str(ENGINE / "integrations/login_runner.py"), "--help"))

    @skipUnless(importlib.util.find_spec("playwright"), "已安装状态实测需先安装 tools/cnki_agent/requirements.txt")
    def test_installed_same_version_but_changed_module_is_not_ready(self):
        script = "import sys, json; sys.path.insert(0, sys.argv[1]); from integrations.cnki_external import package_status; print(json.dumps(package_status()))"
        original_status = json.loads(self.run_python("-c", script, str(ENGINE)))
        self.assertTrue(original_status["installed"])
        module = Path(original_status["location"]).parent / "native_export.py"
        original = module.read_bytes()
        try:
            module.write_bytes(original + b"\n# changed installed source\n")
            result = json.loads(self.run_python("-c", script, str(ENGINE)))
            self.assertTrue(result["integrity_ok"])
            self.assertFalse(result["installed"])
            self.assertIn("源码不匹配", result["installed_error"])
        finally:
            module.write_bytes(original)
