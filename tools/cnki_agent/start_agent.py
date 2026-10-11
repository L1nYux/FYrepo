"""Bootstrap the standalone CNKI Agent; standard library only."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def configured_origins():
    config = HERE / "workbench_origin.json"
    if not config.exists():
        return []
    try:
        data = json.loads(config.read_text(encoding="utf-8-sig"))
        origins = data["allowed_origins"]
        if data.get("schema_version") != 1 or not isinstance(origins, list) or not origins or len(origins) > 10:
            raise ValueError("配置格式错误")
        for origin in origins:
            if not isinstance(origin, str):
                raise ValueError("工作台地址须为文本")
            value = urlsplit(origin)
            if (value.scheme not in ("http", "https") or not value.hostname or value.username
                    or value.password or value.path or value.query or value.fragment
                    or any(char.isspace() for char in origin)):
                raise ValueError("地址须为完整 HTTP/HTTPS 源地址，不含路径")
            _ = value.port
        return origins
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError("工作台地址配置无法读取，请从工作台重新下载完整采集器包。") from exc


def verify_files():
    engine = ROOT / "vendor/sample_llm"
    checker = engine / "integrations/component_integrity.py"
    if not checker.is_file():
        raise RuntimeError("采集器包未完整解压：启动文件旁须保留 tools 和 vendor 文件夹。")
    spec = importlib.util.spec_from_file_location("fyrepo_agent_start_integrity", checker)
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)
    return validator.validate_bundled_component(engine)


def virtualenv_python():
    environment = HERE / ".venv"
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.is_file():
        print("正在建立采集器独立环境……", flush=True)
        subprocess.run([sys.executable, "-m", "venv", str(environment)], check=True)
    subprocess.run([str(python), "-c", "import sys; assert sys.version_info >= (3, 11)"], check=True)
    return python


def install_dependencies(python):
    requirements = HERE / "requirements.txt"
    digest = hashlib.sha256(requirements.read_bytes()).hexdigest()
    marker = HERE / ".venv/requirements.sha256"
    probe = subprocess.run([str(python), "-c", "import pandas, openpyxl, lxml, html5lib, playwright"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not marker.is_file() or marker.read_text().strip() != digest or probe.returncode:
        print("首次运行正在安装采集依赖，需要联网；请等待，不要关闭窗口。", flush=True)
        subprocess.run([str(python), "-m", "pip", "install", "-r", str(requirements)], check=True)
        marker.write_text(digest, encoding="ascii")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="只校验文件和地址，不安装或启动浏览器")
    options, server_args = parser.parse_known_args()
    if sys.version_info < (3, 11):
        raise RuntimeError("请安装 Python 3.11 或更新版本。")
    origins = configured_origins()
    verified = verify_files()
    print(f"采集器文件校验通过（{verified['checked_files']} 文件）。", flush=True)
    if options.check:
        print("允许工作台：" + ", ".join(origins or ["本地工作台默认地址"]), flush=True)
        return 0
    if "--port" not in server_args:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
            if os.name == "nt":
                connection.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            try:
                connection.bind(("127.0.0.1", 8765))
            except OSError as exc:
                raise RuntimeError("8765 端口已被使用。采集器可能已运行，请使用原窗口的连接码，或先关闭旧采集器。") from exc
    python = virtualenv_python()
    install_dependencies(python)
    args = [str(python), str(HERE / "agent_server.py")]
    for origin in origins:
        args.extend(["--allow-origin", origin])
    args.extend(server_args)
    print("启动后请保持此窗口打开，将连接码粘贴回工作台。停止时按 Ctrl+C。", flush=True)
    return subprocess.run(args, cwd=HERE).returncode


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n采集器已停止。")
        raise SystemExit(0)
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        print(f"\n启动未完成：{exc}", file=sys.stderr)
        raise SystemExit(1)
