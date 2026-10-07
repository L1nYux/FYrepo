from __future__ import annotations
import json
from pathlib import Path
import pandas as pd
from .utils import norm

def load_registry(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def build_frame(registry, periods, selected_tiers, selected_journals, main_n, reserve_n, holdout_enabled, holdout_start, holdout_end, holdout_n):
    tier_lookup={j:t for t,js in registry["tiers"].items() for j in js}
    rows=[]; order=1
    for j in selected_journals:
        base=tier_lookup.get(j,"")
        if base not in selected_tiers: continue
        aliases="|".join(registry.get("journal_aliases",{}).get(j,[j]))
        for p in periods:
            tier=registry.get("period_tier_overrides",{}).get(j,{}).get(p["id"],base)
            rows.append({"stratum_id":f"MAIN_{order:04d}","role":"MAIN","journal_family_name":j,"journal_query_names":aliases,"period":p["id"],"start_year":int(p["start_year"]),"end_year":int(p["end_year"]),"tier":tier,"target_n":int(main_n),"reserve_n":int(reserve_n),"cross_disciplinary_journal":1 if j in registry.get("cross_disciplinary",[]) else 0,"frame_order":order}); order+=1
    if holdout_enabled:
        for j in selected_journals:
            base=tier_lookup.get(j,"")
            if base not in selected_tiers: continue
            aliases="|".join(registry.get("journal_aliases",{}).get(j,[j]))
            rows.append({"stratum_id":f"HOLDOUT_{order:04d}","role":"HOLDOUT","journal_family_name":j,"journal_query_names":aliases,"period":"HOLDOUT","start_year":int(holdout_start),"end_year":int(holdout_end),"tier":registry.get("period_tier_overrides",{}).get(j,{}).get("P3",base),"target_n":int(holdout_n),"reserve_n":int(reserve_n),"cross_disciplinary_journal":1 if j in registry.get("cross_disciplinary",[]) else 0,"frame_order":order}); order+=1
    return pd.DataFrame(rows)

def attach_frame(candidates, frame):
    rows=[]
    for rec in candidates.to_dict("records"):
        jr=norm(rec.get("journal","")); yr=int(rec["year"]) if str(rec.get("year","")).isdigit() else None; matched=False
        for fr in frame.to_dict("records"):
            aliases=[norm(x) for x in str(fr["journal_query_names"]).split("|") if str(x).strip()]
            if yr is not None and jr in aliases and int(fr["start_year"]) <= yr <= int(fr["end_year"]):
                x=dict(rec); x.update(fr); x["frame_match_status"]="MATCHED"; rows.append(x); matched=True
        if not matched:
            x=dict(rec); x.update({"stratum_id":"","role":"","period":"","tier":"","journal_family_name":"","cross_disciplinary_journal":0,"frame_match_status":"UNMATCHED","frame_order":999999}); rows.append(x)
    return pd.DataFrame(rows)
