from __future__ import annotations

import hashlib
import json
import tempfile
import zipfile
from pathlib import Path

import pandas as pd

from .utils import parse_cnki


def _write(df, path):
    df.to_csv(path, index=False, encoding="utf-8-sig")


def _frame_fingerprint(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return hashlib.sha256(b"").hexdigest()
    x = df.copy().fillna("")
    cols = sorted(x.columns.tolist())
    x = x[cols].astype(str)
    sort_cols = [c for c in ("stratum_id", "candidate_key", "paper_id", "title") if c in x.columns]
    if sort_cols:
        x = x.sort_values(sort_cols, kind="mergesort")
    payload = x.to_csv(index=False, lineterminator="\n").encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def result_tables(primary, reserve):
    download = []
    evidence = []
    for rec in primary.to_dict("records"):
        ids = parse_cnki(
            rec.get("url", ""), rec.get("cnki_filename", ""), rec.get("cnki_dbcode", "")
        )
        download.append(
            {
                "paper_id": rec.get("paper_id", ""),
                "role": rec.get("sample_role", ""),
                "tier": rec.get("tier", ""),
                "period": rec.get("period", ""),
                "journal": rec.get("journal", ""),
                "year": rec.get("year", ""),
                "issue": rec.get("issue", ""),
                "title": rec.get("title", ""),
                "cnki_url": rec.get("url", ""),
                "doi": rec.get("doi", ""),
                "cnki_record_key": ids["cnki_record_key"],
                "download_status": "待下载",
            }
        )
        need = 1 if ids["record_key_method"] in {"missing", "url_hash"} else 0
        evidence.append(
            {
                "task_id": f"{rec.get('paper_id', '')}-A",
                "paper_id": rec.get("paper_id", ""),
                "type": "论文题录",
                "required": need,
                "status": "待处理" if need else "自动信息已足够",
                "page": rec.get("url", "") or f"精确检索：{rec.get('title', '')}",
                "screenshot_name": f"{rec.get('paper_id', '')}_A_article_record.png" if need else "—",
                "what_to_capture": "题名 + 作者 + 期刊/来源 + 年份/期号；尽量保留地址栏" if need else "无需截图",
            }
        )
    if not primary.empty:
        for i, rec in (
            primary[["journal_family_name", "journal"]]
            .drop_duplicates()
            .reset_index(drop=True)
            .iterrows()
        ):
            evidence.append(
                {
                    "task_id": f"J{i + 1:03d}-B",
                    "paper_id": "—",
                    "type": "期刊当前标签",
                    "required": 1,
                    "status": "待处理",
                    "page": f"打开《{rec['journal']}》CNKI期刊/来源页",
                    "screenshot_name": f"J{i + 1:03d}_B_journal_tags.png",
                    "what_to_capture": "期刊名称 + CNKI当前展示标签；同一期刊只截一次",
                }
            )
    return pd.DataFrame(download), pd.DataFrame(evidence)


def _certificate(primary: pd.DataFrame, reserve: pd.DataFrame, protocol: dict) -> pd.DataFrame:
    pieces = []
    if primary is not None and not primary.empty:
        pieces.append(primary.copy())
    if reserve is not None and not reserve.empty:
        pieces.append(reserve.copy())
    if not pieces:
        return pd.DataFrame()
    x = pd.concat(pieces, ignore_index=True, sort=False)
    x["run_fingerprint"] = protocol.get("run_fingerprint", "")
    wanted = [
        "paper_id",
        "sample_role",
        "reserve_for_role",
        "stratum_id",
        "tier",
        "period",
        "journal",
        "year",
        "issue",
        "title",
        "candidate_key",
        "draw_hash",
        "draw_rank",
        "stratum_pool_size",
        "sampling_method",
        "sampling_seed",
        "protocol_version",
        "run_fingerprint",
    ]
    for c in wanted:
        if c not in x.columns:
            x[c] = ""
    return x[wanted]


def _protocol_markdown(protocol: dict) -> str:
    return f"""# 抽样协议与复现凭证

- 协议版本：`{protocol.get('protocol_version', '')}`
- 抽样方法：**{protocol.get('method_label', '')}** (`{protocol.get('method', '')}`)
- 主样本 seed：`{protocol.get('seed', '')}`
- 备用样本 seed：`{protocol.get('reserve_seed', '')}`
- Sampling frame SHA256：`{protocol.get('sampling_frame_sha256', '')}`
- Candidate registry SHA256：`{protocol.get('candidate_registry_sha256', '')}`
- Run fingerprint：`{protocol.get('run_fingerprint', '')}`

## 规则

{protocol.get('description', '')}

哈希优先级统一使用：

`SHA256(seed | stratum_id | candidate_key)`

其中 `candidate_key` 是论文的稳定候选键；同一份 `sampling_frame.csv`、`candidate_registry.csv`、相同方法和相同 seed 应生成相同排序及样本。

## 如何复核

1. 核对 `sampling_frame.csv` 与 `candidate_registry.csv` 的 SHA256 是否与本文件一致；
2. 按 `sampling_ranking_full.csv` 查看每个抽样格的完整排序；
3. `sampling_certificate.csv` 保存每个最终 MAIN / HOLDOUT / RESERVE 样本的 `draw_hash`、`draw_rank` 和 `paper_id`；
4. 若输入数据、规则或 seed 发生变化，应视为一次新的抽样运行，不应沿用原凭证。
"""


def make_bundle(frame, registry, primary, reserve, issues, out_path, *, audit=None, protocol=None):
    out_path = Path(out_path)
    download, evidence = result_tables(primary, reserve)
    audit = audit if audit is not None else pd.DataFrame()
    protocol = dict(protocol or {})
    protocol.setdefault("protocol_version", "sampling_protocol_v1")
    protocol["sampling_frame_sha256"] = _frame_fingerprint(frame)
    protocol["candidate_registry_sha256"] = _frame_fingerprint(registry)
    fingerprint_payload = "|".join(
        [
            str(protocol.get("protocol_version", "")),
            str(protocol.get("method", "")),
            str(protocol.get("seed", "")),
            protocol["sampling_frame_sha256"],
            protocol["candidate_registry_sha256"],
        ]
    )
    protocol["run_fingerprint"] = hashlib.sha256(fingerprint_payload.encode("utf-8")).hexdigest()

    certificate = _certificate(primary, reserve, protocol)
    protocol_path = out_path.with_name("sampling_protocol.json")
    certificate_path = out_path.with_name("sampling_certificate.csv")
    ranking_path = out_path.with_name("sampling_ranking_full.csv")
    protocol_path.write_text(json.dumps(protocol, ensure_ascii=False, indent=2), encoding="utf-8")
    _write(certificate, certificate_path)
    _write(audit, ranking_path)

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write(frame, root / "sampling_frame.csv")
        _write(registry, root / "candidate_registry.csv")
        _write(primary, root / "selected_samples.csv")
        _write(reserve, root / "reserve_samples.csv")
        _write(issues, root / "sampling_issues.csv")
        _write(download, root / "download_queue.csv")
        _write(evidence, root / "evidence_queue.csv")
        _write(certificate, root / "sampling_certificate.csv")
        _write(audit, root / "sampling_ranking_full.csv")
        (root / "sampling_protocol.json").write_text(
            json.dumps(protocol, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (root / "SAMPLING_PROTOCOL.md").write_text(
            _protocol_markdown(protocol), encoding="utf-8"
        )

        safe = pd.DataFrame(
            [
                {
                    "paper_id": r.get("paper_id", ""),
                    "version_stage": "T2",
                    "readiness_status": "pending",
                    "notes": "PDF保留原文件名，后续自动绑定",
                }
                for r in primary.to_dict("records")
            ]
        )
        labels = pd.DataFrame(
            [
                {
                    "paper_id": r.get("paper_id", ""),
                    "true_journal_name": r.get("journal", ""),
                    "journal_family_name": r.get("journal_family_name", ""),
                    "publication_year": r.get("year", ""),
                    "period": r.get("period", ""),
                    "true_tier": r.get("tier", ""),
                    "true_title": r.get("title", ""),
                    "true_author": r.get("authors", ""),
                }
                for r in primary.to_dict("records")
            ]
        )
        _write(safe, root / "safe_sample_manifest.csv")
        _write(labels, root / "labels_vault_seed_DO_NOT_COMMIT.csv")
        (root / "README_NEXT.txt").write_text(
            "先保留sampling_protocol与sampling_certificate作为抽样凭证；只下载download_queue中的正式样本/HOLDOUT PDF；PDF不要改名。按evidence_queue只补required=1的证据。",
            encoding="utf-8",
        )
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
            for p in root.rglob("*"):
                if p.is_file():
                    z.write(p, p.relative_to(root))

    return (
        download,
        evidence,
        str(out_path),
        str(protocol_path),
        str(certificate_path),
        str(ranking_path),
        protocol,
        certificate,
    )
