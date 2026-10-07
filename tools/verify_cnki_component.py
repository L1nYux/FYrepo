"""Offline archive verification; --install also exercises the real Agent installer."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "vendor/sample_llm"
sys.path.insert(0, str(ROOT))
from integrations.component_integrity import validate_bundled_component  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="校验正式 CNKI 采集包，不访问知网或登录资料")
    parser.add_argument("--install", action="store_true", help="在当前 Python 环境真实离线安装并检查采集/合并入口；不安装浏览器")
    args = parser.parse_args()
    try:
        verified = validate_bundled_component(ROOT)
        print(json.dumps(verified, ensure_ascii=False, indent=2))
        if args.install:
            from integrations.cnki_external import install_package, package_status
            for event in install_package(install_browser=False):
                print(event["message"], flush=True)
            status = package_status()
            if not status["installed"]:
                raise RuntimeError(status["installed_error"] or "组件没有正确安装")
            print("OFFLINE_INSTALL_OK: version=0.2.0; collector and merge entry points loaded", flush=True)
        else:
            print("ARCHIVE_INTEGRITY_OK", flush=True)
        return 0
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
