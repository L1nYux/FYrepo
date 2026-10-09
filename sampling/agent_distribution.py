"""Build the public Agent download from verified code, never from runtime folders."""
import hashlib
import importlib.util
import io
import json
import zipfile
from pathlib import Path
from django.conf import settings


class AgentPackageError(RuntimeError):
    pass


AGENT_FILES = (
    "START_CNKI_AGENT_WINDOWS.cmd", "START_CNKI_AGENT_MAC_LINUX.sh",
    "tools/cnki_agent/start_agent.py", "tools/cnki_agent/agent_server.py",
    "tools/cnki_agent/run_agent_windows.cmd", "tools/cnki_agent/run_agent_mac_linux.sh",
    "tools/cnki_agent/requirements.txt", "tools/cnki_agent/README.md",
)


def build_agent_package(origin, *, base_dir=None):
    root = Path(base_dir or settings.BASE_DIR).resolve()
    engine = root / "vendor/sample_llm"
    try:
        spec = importlib.util.spec_from_file_location(
            "fyrepo_distribution_integrity", engine / "integrations/component_integrity.py")
        validator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(validator)
        verified = validator.validate_bundled_component(engine)
        manifest_bytes = (root / "vendor/SAMPLE_LLM_SOURCE.json").read_bytes()
        manifest = json.loads(manifest_bytes)
        names = list(AGENT_FILES) + ["vendor/SAMPLE_LLM_SOURCE.json"]
        names += ["vendor/sample_llm/" + entry["path"] for entry in manifest["files"]]
        files = {}
        for name in names:
            path = (root / name).resolve()
            if not path.is_relative_to(root):
                raise AgentPackageError("采集器文件路径无效。")
            payload = path.read_bytes()
            if name.endswith(".cmd"):
                payload = payload.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            files[name] = payload
        files["tools/cnki_agent/workbench_origin.json"] = json.dumps(
            {"schema_version": 1, "allowed_origins": [origin]}, ensure_ascii=False, indent=2).encode("utf-8")
        files["README_START_HERE.md"] = (
            "# FYrepo 本机知网采集器\n\n"
            f"本包已配置工作台地址：{origin}\n\n"
            "1. 完整解压 ZIP，保留 tools 与 vendor 文件夹。\n"
            "2. Windows 双击 START_CNKI_AGENT_WINDOWS.cmd；macOS / Linux 执行 "
            "bash START_CNKI_AGENT_MAC_LINUX.sh。\n"
            "3. 需要 Python 3.11+。第一次运行自动建立独立环境、安装依赖，请保持窗口打开。\n"
            "4. 复制窗口显示的连接码回到网页，依次检查连接、安装组件、打开知网登录、登录完成。\n"
            "5. 知网机构认证和验证码由本人完成。连接码与登录资料保留在本机。\n\n"
            "覆盖升级时合并同名文件；保留 .venv、tools/cnki_agent/runtime 与 "
            "vendor/sample_llm/runtime_outputs。不要删除原目录。\n"
            "故障排查见 tools/cnki_agent/README.md。\n"
        ).encode("utf-8")
        files["AGENT_PACKAGE.json"] = json.dumps({
            "schema_version": 1, "release": "2026-10-09", "workbench_origin": origin,
            "component_commit": verified["commit"], "checked_engine_files": verified["checked_files"],
            "files": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())},
        }, ensure_ascii=False, indent=2).encode("utf-8")
        result = io.BytesIO()
        with zipfile.ZipFile(result, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name, payload in sorted(files.items()):
                info = zipfile.ZipInfo("FYrepo-CNKI-Agent/" + name, (2026, 10, 9, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (0o100755 if name.endswith(".sh") else 0o100644) << 16
                archive.writestr(info, payload)
        result.seek(0)
        return result
    except AgentPackageError:
        raise
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        raise AgentPackageError(f"采集器下载暂不可用：{exc}") from exc
