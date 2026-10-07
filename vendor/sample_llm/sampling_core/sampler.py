from __future__ import annotations

from collections import defaultdict

import pandas as pd

from .utils import clean, stable_hash

PROTOCOL_VERSION = "sampling_protocol_v1"
METHOD_HASH_ISSUE_BALANCED = "hash_issue_balanced"
METHOD_HASH_SIMPLE = "hash_simple"

METHOD_LABELS = {
    METHOD_HASH_ISSUE_BALANCED: "确定性哈希 + 期号均衡（推荐）",
    METHOD_HASH_SIMPLE: "确定性哈希直接排序",
}

METHOD_DESCRIPTIONS = {
    METHOD_HASH_ISSUE_BALANCED: (
        "在每个期刊×时期×角色的抽样格内，对 candidate_key 计算 "
        "SHA256(seed | stratum_id | candidate_key)；先在各期号内部按哈希值排序，"
        "再按期号轮转抽取，降低样本集中在同一期号的概率。相同候选池、seed 和规则会得到完全相同结果。"
    ),
    METHOD_HASH_SIMPLE: (
        "在每个期刊×时期×角色的抽样格内，对 candidate_key 计算 "
        "SHA256(seed | stratum_id | candidate_key)，按哈希值从小到大直接排序并抽取。"
        "相同候选池、seed 和规则会得到完全相同结果。"
    ),
}


def method_label(method: str) -> str:
    return METHOD_LABELS.get(method, method)


def method_description(method: str) -> str:
    return METHOD_DESCRIPTIONS.get(method, "")


def _issue(rec):
    return f"{clean(rec.get('year'))}-{clean(rec.get('issue')) or rec['candidate_key'][:8]}"


def _hash_record(rec: dict, seed: str, sid: str) -> dict:
    x = dict(rec)
    x["draw_hash"] = stable_hash(seed, sid, x["candidate_key"])
    x["issue_group"] = _issue(x)
    return x


def _rank_hash_issue_balanced(pool: pd.DataFrame, seed: str, sid: str) -> list[dict]:
    groups = defaultdict(list)
    for rec in pool.to_dict("records"):
        x = _hash_record(rec, seed, sid)
        groups[x["issue_group"]].append(x)
    for key in groups:
        groups[key].sort(key=lambda r: (r["draw_hash"], r["candidate_key"]))
    issue_order = sorted(groups, key=lambda key: (groups[key][0]["draw_hash"], key))
    ranked: list[dict] = []
    round_i = 0
    while True:
        added = False
        for key in issue_order:
            if round_i < len(groups[key]):
                ranked.append(groups[key][round_i])
                added = True
        if not added:
            break
        round_i += 1
    for i, rec in enumerate(ranked, 1):
        rec["draw_rank"] = i
    return ranked


def _rank_hash_simple(pool: pd.DataFrame, seed: str, sid: str) -> list[dict]:
    ranked = [_hash_record(rec, seed, sid) for rec in pool.to_dict("records")]
    ranked.sort(key=lambda r: (r["draw_hash"], r["candidate_key"]))
    for i, rec in enumerate(ranked, 1):
        rec["draw_rank"] = i
    return ranked


def _rank(pool: pd.DataFrame, seed: str, sid: str, method: str) -> list[dict]:
    if method == METHOD_HASH_SIMPLE:
        return _rank_hash_simple(pool, seed, sid)
    if method == METHOD_HASH_ISSUE_BALANCED:
        return _rank_hash_issue_balanced(pool, seed, sid)
    raise ValueError(f"未知抽样方法：{method}")


def _audit_rows(
    ranked: list[dict],
    *,
    method: str,
    seed: str,
    stage: str,
    role: str,
    sid: str,
    selected_keys: set[str],
    paper_id_by_key: dict[str, str],
) -> list[dict]:
    pool_size = len(ranked)
    rows = []
    for rec in ranked:
        rows.append(
            {
                "protocol_version": PROTOCOL_VERSION,
                "sampling_method": method,
                "sampling_method_label": method_label(method),
                "sampling_seed": seed,
                "sampling_stage": stage,
                "role": role,
                "stratum_id": sid,
                "pool_size": pool_size,
                "candidate_key": rec.get("candidate_key", ""),
                "journal": rec.get("journal", ""),
                "year": rec.get("year", ""),
                "issue": rec.get("issue", ""),
                "title": rec.get("title", ""),
                "issue_group": rec.get("issue_group", ""),
                "draw_hash": rec.get("draw_hash", ""),
                "draw_rank": rec.get("draw_rank", ""),
                "selected": 1 if rec.get("candidate_key") in selected_keys else 0,
                "paper_id": paper_id_by_key.get(rec.get("candidate_key", ""), ""),
            }
        )
    return rows


def sample(
    registry,
    frame,
    seed="law_sampling_v1",
    method=METHOD_HASH_ISSUE_BALANCED,
    main_prefix="P",
    hold_prefix="H",
    reserve_prefix="R",
    width=3,
):
    unresolved = registry[
        (registry["eligibility_status"] == "UNCERTAIN")
        & (~registry["decision"].isin(["include", "exclude"]))
    ]
    if len(unresolved):
        raise ValueError(f"仍有 {len(unresolved)} 条UNCERTAIN未确认")

    if method not in METHOD_LABELS:
        raise ValueError(f"未知抽样方法：{method}")

    seed = str(seed or "law_sampling_v1")
    eligible = registry[registry["decision"] == "include"].copy()
    used: set[str] = set()
    primary: list[dict] = []
    reserves: list[dict] = []
    issues: list[dict] = []
    audit: list[dict] = []
    ctr = {"MAIN": 1, "HOLDOUT": 1}
    pref = {"MAIN": main_prefix, "HOLDOUT": hold_prefix}

    for role in ["MAIN", "HOLDOUT"]:
        for fr in frame[frame["role"] == role].sort_values("frame_order").to_dict("records"):
            sid = fr["stratum_id"]
            target = int(fr["target_n"])
            pool = eligible[
                (eligible["stratum_id"] == sid)
                & (~eligible["candidate_key"].isin(used))
            ]
            ranked = _rank(pool, seed, sid, method)
            chosen = ranked[:target]
            if len(chosen) < target:
                issues.append(
                    {
                        "stratum_id": sid,
                        "role": role,
                        "requested": target,
                        "selected": len(chosen),
                        "issue": "主样本不足",
                    }
                )

            selected_keys: set[str] = set()
            paper_id_by_key: dict[str, str] = {}
            for rec in chosen:
                x = dict(rec)
                x["sample_role"] = role
                x["paper_id"] = f"{pref[role]}{ctr[role]:0{width}d}"
                x["sampling_method"] = method
                x["sampling_seed"] = seed
                x["protocol_version"] = PROTOCOL_VERSION
                x["stratum_pool_size"] = len(ranked)
                ctr[role] += 1
                primary.append(x)
                used.add(x["candidate_key"])
                selected_keys.add(x["candidate_key"])
                paper_id_by_key[x["candidate_key"]] = x["paper_id"]

            audit.extend(
                _audit_rows(
                    ranked,
                    method=method,
                    seed=seed,
                    stage=f"{role}_DRAW",
                    role=role,
                    sid=sid,
                    selected_keys=selected_keys,
                    paper_id_by_key=paper_id_by_key,
                )
            )

    rc = 1
    reserve_seed = seed + "|reserve"
    for fr in frame.sort_values("frame_order").to_dict("records"):
        rn = int(fr["reserve_n"])
        sid = fr["stratum_id"]
        if rn <= 0:
            continue
        pool = eligible[
            (eligible["stratum_id"] == sid)
            & (~eligible["candidate_key"].isin(used))
        ]
        ranked = _rank(pool, reserve_seed, sid, method)
        chosen = ranked[:rn]
        selected_keys: set[str] = set()
        paper_id_by_key: dict[str, str] = {}
        for j, rec in enumerate(chosen, 1):
            x = dict(rec)
            x["sample_role"] = "RESERVE"
            x["paper_id"] = f"{reserve_prefix}{rc:0{max(width, 3)}d}"
            x["reserve_rank"] = j
            x["reserve_for_role"] = fr["role"]
            x["sampling_method"] = method
            x["sampling_seed"] = reserve_seed
            x["protocol_version"] = PROTOCOL_VERSION
            x["stratum_pool_size"] = len(ranked)
            reserves.append(x)
            used.add(x["candidate_key"])
            selected_keys.add(x["candidate_key"])
            paper_id_by_key[x["candidate_key"]] = x["paper_id"]
            rc += 1
        audit.extend(
            _audit_rows(
                ranked,
                method=method,
                seed=reserve_seed,
                stage="RESERVE_DRAW",
                role=fr["role"],
                sid=sid,
                selected_keys=selected_keys,
                paper_id_by_key=paper_id_by_key,
            )
        )

    return (
        pd.DataFrame(primary),
        pd.DataFrame(reserves),
        pd.DataFrame(issues),
        pd.DataFrame(audit),
    )
