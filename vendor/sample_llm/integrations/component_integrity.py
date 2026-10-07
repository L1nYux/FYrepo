"""FYrepo validation for the rebuilt, pinned CNKI component (no network access)."""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import re
import zipfile
import zlib
from email.parser import BytesParser
from pathlib import Path, PurePosixPath

PACKAGE_VERSION = "0.2.0"
PINNED_COMMIT = "4bdf8e108c81c4d1a0590377aec1238f534e1a18"
ARCHIVE_NAME = "cnki-metadata-exporter-0.2.0-4bdf8e1.zip"
WHEEL_NAME = "cnki_metadata_exporter-0.2.0-py3-none-any.whl"
SOURCE_PREFIX = "cnki-metadata-exporter-4bdf8e1/"
DIST_INFO = f"cnki_metadata_exporter-{PACKAGE_VERSION}.dist-info/"
MODULE_NAMES = ("__init__.py", "cli.py", "exporter.py", "merge_metadata.py", "native_export.py", "queries.py")


class ComponentIntegrityError(RuntimeError):
    pass


def _fail(message):
    raise ComponentIntegrityError(f"采集组件完整性校验失败：{message}。请重新下载并完整覆盖 FYrepo 软件包。")


def _check_zip(archive, label):
    names = archive.namelist()
    if len(names) != len(set(names)):
        _fail(f"{label} 包含重复条目")
    bad = archive.testzip()
    if bad:
        _fail(f"{label} 的 {bad} CRC 校验不通过")


def validate_bundled_component(root: Path) -> dict:
    """Check the active manifest, both archives, wheel RECORD, and source equivalence."""
    root = Path(root).resolve()
    try:
        manifest = json.loads((root.parent / "SAMPLE_LLM_SOURCE.json").read_text(encoding="utf-8"))
        component = manifest["component"]
        if (manifest["schema_version"] != 2 or component["commit"] != PINNED_COMMIT
                or component["version"] != PACKAGE_VERSION):
            _fail("来源清单的组件版本或固定提交不匹配")
        entries = manifest["files"]
        if not isinstance(entries, list) or not entries:
            _fail("来源清单没有文件记录")
        expected = {}
        for entry in entries:
            name, digest = entry["path"], entry["sha256"]
            path = PurePosixPath(name)
            if (path.is_absolute() or ".." in path.parts or "\\" in name
                    or name in expected or not re.fullmatch(r"[0-9a-f]{64}", digest)):
                _fail("来源清单的文件路径或 SHA256 不合法")
            file = (root / name).resolve()
            if not file.is_relative_to(root) or hashlib.sha256(file.read_bytes()).hexdigest() != digest:
                _fail(f"{name} SHA256 不匹配")
            expected[name] = digest
        for name in (ARCHIVE_NAME, WHEEL_NAME):
            if f"third_party/{name}" not in expected:
                _fail(f"来源清单缺少 {name}")

        with (zipfile.ZipFile(root / "third_party" / ARCHIVE_NAME) as source,
              zipfile.ZipFile(root / "third_party" / WHEEL_NAME) as wheel):
            _check_zip(source, ARCHIVE_NAME)
            _check_zip(wheel, WHEEL_NAME)
            metadata = BytesParser().parsebytes(wheel.read(DIST_INFO + "METADATA"))
            if metadata["Name"] != "cnki-metadata-exporter" or metadata["Version"] != PACKAGE_VERSION:
                _fail("wheel 的包名称或版本不匹配")
            if "Root-Is-Purelib: true" not in wheel.read(DIST_INFO + "WHEEL").decode():
                _fail("wheel 不是预期的纯 Python 包")
            records = list(csv.reader(io.StringIO(wheel.read(DIST_INFO + "RECORD").decode("utf-8"))))
            names = [row[0] for row in records]
            if len(names) != len(set(names)) or set(names) != set(wheel.namelist()):
                _fail("wheel RECORD 与实际文件清单不一致")
            for name, digest, size in records:
                if name == DIST_INFO + "RECORD":
                    if digest or size:
                        _fail("wheel RECORD 自记录不合法")
                    continue
                data = wheel.read(name)
                actual = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode("ascii")
                if digest != "sha256=" + actual or size != str(len(data)):
                    _fail(f"wheel RECORD 中的 {name} 不匹配")
            modules = {}
            for name in MODULE_NAMES:
                member = "cnki_metadata_exporter/" + name
                data = wheel.read(member)
                if data != source.read(SOURCE_PREFIX + "src/" + member):
                    _fail(f"wheel 的 {name} 与固定源码快照不一致")
                modules[name] = hashlib.sha256(data).hexdigest()
            if wheel.read(DIST_INFO + "licenses/LICENSE") != source.read(SOURCE_PREFIX + "LICENSE"):
                _fail("wheel 与源码许可证不一致")
        return {"commit": PINNED_COMMIT, "version": PACKAGE_VERSION, "module_sha256": modules,
                "checked_files": len(expected), "wheel_sha256": expected["third_party/" + WHEEL_NAME],
                "archive_sha256": expected["third_party/" + ARCHIVE_NAME]}
    except ComponentIntegrityError:
        raise
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, zlib.error, RuntimeError) as exc:
        _fail(f"安装包或来源清单无法读取（{type(exc).__name__}: {exc}）")
