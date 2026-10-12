"""Stage application code and verify its Agent download before service cutover."""
import argparse
import importlib.util
import json
import shutil
import sys
import hashlib
from pathlib import Path


APPLICATION_ITEMS = (
    "manage.py", "requirements.txt", "config", "core", "aihub", "sampling",
    "tools", "templates", "static", "deploy", "desktop/release-info.json",
)


def stage_release(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or destination.is_relative_to(source) or source.is_relative_to(destination):
        raise ValueError("源码和发布目录必须独立，不能相互包含。")
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("发布目录须为空，请使用新的发布目录。")

    spec = importlib.util.spec_from_file_location(
        "fyrepo_release_distribution", source / "sampling/agent_distribution.py")
    distribution = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(distribution)
    # The explicit root keeps this check independent of Django or a virtualenv.
    distribution.build_agent_package("https://release-check.invalid", base_dir=source).close()
    manifest = json.loads((source / "vendor/SAMPLE_LLM_SOURCE.json").read_text(encoding="utf-8"))
    agent_files = list(distribution.AGENT_FILES) + ["vendor/SAMPLE_LLM_SOURCE.json"]
    agent_files += ["vendor/sample_llm/" + entry["path"] for entry in manifest["files"]]
    token_manifest=source/'vendor/tokenizers/SOURCE.json'
    if token_manifest.exists():
        token_data=json.loads(token_manifest.read_text(encoding='utf-8'))
        agent_files+=['vendor/tokenizers/SOURCE.json','vendor/tokenizers/LICENSE']
        for entry in token_data['files']:
            name=entry['file']
            if not name or Path(name).name!=name:raise ValueError('Invalid tokenizer path')
            if hashlib.sha256((token_manifest.parent/name).read_bytes()).hexdigest()!=entry['sha256']:
                raise ValueError('Tokenizer hash mismatch')
            agent_files.append('vendor/tokenizers/'+name)

    for name in APPLICATION_ITEMS:
        item = source / name
        if not item.exists():
            raise FileNotFoundError(f"发布源码缺少必需文件：{name}")

    destination.mkdir(parents=True, exist_ok=True)
    for name in APPLICATION_ITEMS + tuple(agent_files):
        item, target = source / name, destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if item.is_dir():
            shutil.copytree(item, target, ignore=shutil.ignore_patterns(
                "__pycache__", "*.pyc", "*.pyo", ".venv", "venv", "node_modules", "runtime", "runtime_outputs",
                ".env", "*.sqlite3", "*.log", "workbench_origin.json", "browser-profile"))
        else:
            shutil.copy2(item, target)

    # Verify the copied release, not just the complete repository checkout.
    distribution.build_agent_package("https://release-check.invalid", base_dir=destination).close()
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        destination = stage_release(args.source, args.destination)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        print(f"发布准备失败：{exc}", file=sys.stderr)
        return 1
    print(f"发布文件与采集器下载包校验通过：{destination}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
