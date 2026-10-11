"""Anonymous downloads, source integrity and extracted standalone startup."""
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch
from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from .agent_distribution import AGENT_FILES, AgentPackageError, build_agent_package


class AgentDownloadViewTests(TestCase):
    def test_login_and_public_instructions_expose_download_before_login(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, reverse("sampling:agent_download"))
        response = self.client.get(reverse("sampling:agent_setup"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "START_CNKI_AGENT_WINDOWS.cmd")
        self.assertNotContains(response, 'id="workspace-navigation"')

    def test_anonymous_zip_contains_this_workbench_origin_and_complete_engine(self):
        response = self.client.get(reverse("sampling:agent_download"), secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/zip")
        self.assertIn("attachment;", response["Content-Disposition"])
        with zipfile.ZipFile(io.BytesIO(b"".join(response.streaming_content))) as archive:
            self.assertIsNone(archive.testzip())
            prefix = "FYrepo-CNKI-Agent/"
            origin = json.loads(archive.read(prefix + "tools/cnki_agent/workbench_origin.json"))
            self.assertEqual(origin["allowed_origins"], ["https://testserver"])
            self.assertIn(prefix + "START_CNKI_AGENT_WINDOWS.cmd", archive.namelist())
            self.assertIn(prefix + "vendor/sample_llm/integrations/pdf_downloader.py", archive.namelist())
            self.assertIn(prefix + "vendor/sample_llm/third_party/cnki_metadata_exporter-0.2.0-py3-none-any.whl", archive.namelist())
            self.assertNotIn(b"\n", archive.read(prefix + "START_CNKI_AGENT_WINDOWS.cmd").replace(b"\r\n", b""))

    def test_distribution_error_returns_instructions_with_503(self):
        with patch("sampling.views.build_agent_package", side_effect=AgentPackageError("来源文件 SHA256 不匹配")):
            response = self.client.get(reverse("sampling:agent_download"))
        self.assertEqual(response.status_code, 503)
        self.assertContains(response, "SHA256 不匹配", status_code=503)


class AgentPackageTests(SimpleTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "source"
        manifest = json.loads((settings.BASE_DIR / "vendor/SAMPLE_LLM_SOURCE.json").read_text())
        names = list(AGENT_FILES) + ["vendor/SAMPLE_LLM_SOURCE.json"]
        names += ["vendor/sample_llm/" + entry["path"] for entry in manifest["files"]]
        for name in names:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(settings.BASE_DIR / name, target)

    def test_whitelist_excludes_runtime_cookies_database_and_environment(self):
        for name in ("vendor/sample_llm/runtime_outputs/cnki_master_profile/Default/Network/Cookies",
                     "tools/cnki_agent/runtime/private-job.json", "data/workbench.sqlite3", ".env",
                     "tools/cnki_agent/.venv/private.py"):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"private-source-test-fixture")
        with zipfile.ZipFile(build_agent_package("https://workbench.example", base_dir=self.root)) as archive:
            self.assertFalse(any("runtime" in name or ".venv" in name or ".sqlite3" in name or name.endswith("/.env") for name in archive.namelist()))
            self.assertNotIn(b"private-source-test-fixture", b"".join(archive.read(name) for name in archive.namelist()))

    def test_corrupt_component_prevents_distribution(self):
        wheel = self.root / "vendor/sample_llm/third_party/cnki_metadata_exporter-0.2.0-py3-none-any.whl"
        wheel.write_bytes(b"corrupt")
        with self.assertRaisesRegex(AgentPackageError, "SHA256"):
            build_agent_package("https://workbench.example", base_dir=self.root)

    def test_extracted_package_checks_without_repository_or_django(self):
        extraction = self.root.parent / "extracted"
        with zipfile.ZipFile(build_agent_package("https://workbench.example", base_dir=self.root)) as archive:
            archive.extractall(extraction)
        result = subprocess.run([sys.executable, "-S", str(extraction / "FYrepo-CNKI-Agent/tools/cnki_agent/start_agent.py"), "--check"],
            capture_output=True, text=True, encoding="utf-8", timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("23 文件", result.stdout)
        self.assertIn("https://workbench.example", result.stdout)

    def test_invalid_origin_config_has_readable_error(self):
        spec = importlib.util.spec_from_file_location("fyrepo_test_start_agent", self.root / "tools/cnki_agent/start_agent.py")
        bootstrap = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bootstrap)
        config = self.root / "tools/cnki_agent/workbench_origin.json"
        for origins in (["https://workbench.example/path"], [123], ["https://user:password@workbench.example"]):
            with self.subTest(origins=origins):
                config.write_text(json.dumps({"schema_version": 1, "allowed_origins": origins}))
                with self.assertRaisesRegex(RuntimeError, "重新下载"):
                    bootstrap.configured_origins()
