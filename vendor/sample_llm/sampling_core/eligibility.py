from __future__ import annotations
import json
from pathlib import Path
import pandas as pd
from .utils import clean

def load_rules(path): return json.loads(Path(path).read_text(encoding="utf-8"))
def classify(df, rules):
    rows=[]; hard=rules["hard_exclude_title_terms"]; uncertain=rules["uncertain_title_terms"]; prefixes=tuple(rules.get("law_clc_prefixes",["D9"]))
    for rec in df.to_dict("records"):
        title=clean(rec.get("title")); clc=clean(rec.get("clc")).upper(); status="ELIGIBLE_AUTO"; reason="研究论文候选"
        if rec.get("frame_match_status")!="MATCHED": status,reason="HOLD_METADATA","未匹配抽样方案"
        elif not title or not clean(rec.get("journal")) or not clean(rec.get("year")): status,reason="HOLD_METADATA","缺题名/期刊/年份"
        elif any(t in title for t in hard):
            term=next(t for t in hard if t in title); status,reason="EXCLUDED_AUTO",f"标题命中排除词：{term}"
        elif any(t in title for t in uncertain):
            term=next(t for t in uncertain if t in title); status,reason="UNCERTAIN",f"需人工确认：{term}"
        elif int(rec.get("cross_disciplinary_journal",0) or 0)==1 and not (clc and clc.startswith(prefixes)):
            status,reason="UNCERTAIN","跨学科期刊：需确认是否为法学论文"
        x=dict(rec); x["eligibility_status"]=status; x["eligibility_reason"]=reason; x["decision"]="include" if status=="ELIGIBLE_AUTO" else ("exclude" if status in {"EXCLUDED_AUTO","HOLD_METADATA"} else ""); rows.append(x)
    return pd.DataFrame(rows)
