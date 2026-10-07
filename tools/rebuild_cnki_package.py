"""Rebuild the CNKI archives from the original pinned Git tree, never damaged ZIPs."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
ROOT = BASE / "vendor/sample_llm"
sys.path.insert(0, str(ROOT))
from integrations.component_integrity import (  # noqa: E402
    ARCHIVE_NAME, WHEEL_NAME, PACKAGE_VERSION, PINNED_COMMIT, SOURCE_PREFIX, validate_bundled_component,
)

BUILD_TOOLS = {"build": "1.4.0", "hatchling": "1.28.0"}


def git(source, *args):
    return subprocess.check_output(["git", "-C", str(source), *args], text=True).strip()


def rebuild(source):
    for name, version in BUILD_TOOLS.items():
        if importlib.metadata.version(name) != version:
            raise RuntimeError(f"构建工具需固定为 {name}=={version}")
    if git(source, "rev-parse", PINNED_COMMIT + "^{commit}") != PINNED_COMMIT:
        raise RuntimeError("未找到固定上游提交")
    timestamp = git(source, "show", "-s", "--format=%ct", PINNED_COMMIT)
    tree = git(source, "rev-parse", PINNED_COMMIT + "^{tree}")
    with tempfile.TemporaryDirectory(prefix="fyrepo-cnki-build-") as temp:
        temp = Path(temp)
        archive = temp / ARCHIVE_NAME
        subprocess.run(["git", "-C", str(source), "archive", "--format=zip",
                        "--prefix=" + SOURCE_PREFIX, "--output=" + str(archive), PINNED_COMMIT], check=True)
        with zipfile.ZipFile(archive) as package:
            if package.testzip():
                raise RuntimeError("Git 源码快照 CRC 不通过")
            package.extractall(temp / "source")
        checkout = temp / "source" / SOURCE_PREFIX
        env = {**os.environ, "SOURCE_DATE_EPOCH": timestamp}
        subprocess.run([sys.executable, "-m", "build", "--wheel", "--no-isolation",
                        "--outdir", str(temp / "dist"), str(checkout)], env=env, check=True)
        wheel = temp / "dist" / WHEEL_NAME
        with zipfile.ZipFile(wheel) as package:
            if package.testzip():
                raise RuntimeError("新构建 wheel CRC 不通过")
        if (checkout / "LICENSE").read_bytes() != (ROOT / "third_party/cnki-metadata-exporter.LICENSE.txt").read_bytes():
            raise RuntimeError("源码许可证与保留的上游许可证不匹配")
        shutil.copyfile(archive, ROOT / "third_party" / ARCHIVE_NAME)
        shutil.copyfile(wheel, ROOT / "third_party" / WHEEL_NAME)

    manifest_path = ROOT.parent / "SAMPLE_LLM_SOURCE.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    original = {entry["path"]: entry for entry in manifest["files"]}
    files = []
    for name in sorted(set(original) | {"integrations/component_integrity.py"}):
        entry = {"path": name, "sha256": hashlib.sha256((ROOT / name).read_bytes()).hexdigest()}
        prior = original.get(name, {})
        upstream = prior.get("upstream_sha256", prior.get("sha256"))
        if upstream and prior.get("origin") != "fyrepo-added":
            entry["upstream_sha256"] = upstream
            entry["origin"] = "sample-llm" if upstream == entry["sha256"] else "fyrepo-h1"
        else:
            entry["origin"] = "fyrepo-added"
        files.append(entry)
    manifest.update(schema_version=2, files=files, component={
        "repository": "https://github.com/JYao-Chen/cnki-metadata-exporter",
        "commit": PINNED_COMMIT, "source_tree": tree, "version": PACKAGE_VERSION,
        "source_archive": ARCHIVE_NAME, "wheel": WHEEL_NAME,
        "build": {"frontend": "build==1.4.0", "backend": "hatchling==1.28.0",
                  "source_date_epoch": int(timestamp), "command": "python tools/rebuild_cnki_package.py --source <upstream-git-checkout>"},
        "repair": "H1: replaced invalid archives from sample-llm with a Git archive and an unmodified upstream wheel build",
    })
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(validate_bundled_component(ROOT), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="从固定上游 Git 源码重建 CNKI 安装包和来源清单")
    parser.add_argument("--source", type=Path, required=True, help="JYao-Chen/cnki-metadata-exporter 的 Git checkout")
    args = parser.parse_args()
    rebuild(args.source.resolve())
