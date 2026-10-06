from __future__ import annotations
import json, re
from pathlib import Path
import pandas as pd
from .utils import clean, candidate_key, parse_cnki
ALIASES={"题名":"title","论文题名":"title","title":"title","作者":"authors","authors":"authors","author":"authors","文献来源":"journal","来源":"journal","期刊":"journal","journal":"journal","source":"journal","年":"year","年份":"year","发表时间":"year","出版日期":"year","year":"year","pub_date":"year","期":"issue","期号":"issue","issue":"issue","卷":"volume","volume":"volume","DOI":"doi","doi":"doi","URL":"url","网址":"url","链接":"url","detail_url":"url","url":"url","关键词":"keywords","keywords":"keywords","摘要":"abstract","abstract":"abstract","中图分类号":"clc","CLC":"clc","clc":"clc","来源库":"database","database":"database","文献类型":"article_type","article_type":"article_type","kind":"article_type","filename":"cnki_filename","cnki_filename":"cnki_filename","dbcode":"cnki_dbcode","cnki_dbcode":"cnki_dbcode"}
CANON=["title","authors","journal","year","issue","volume","doi","url","keywords","abstract","clc","database","article_type","cnki_filename","cnki_dbcode"]
def _normalise(df, source_file):
    df=df.rename(columns={c:ALIASES.get(clean(c),clean(c)) for c in df.columns}).copy()
    if df.columns.duplicated().any():
        cols={}
        for c in dict.fromkeys(df.columns):
            part=df.loc[:,df.columns==c]
            cols[c]=part.iloc[:,0] if part.shape[1]==1 else part.apply(lambda r: next((clean(v) for v in r if clean(v)),""),axis=1)
        df=pd.DataFrame(cols)
    for c in CANON:
        if c not in df.columns: df[c]=""
        df[c]=df[c].map(clean)
    df["year"]=df["year"].map(lambda v:(re.search(r"(?:19|20)\d{2}",v).group(0) if re.search(r"(?:19|20)\d{2}",v) else ""))
    rows=[]
    for rec in df[CANON].to_dict("records"):
        rec.update(parse_cnki(rec.get("url",""),rec.get("cnki_filename",""),rec.get("cnki_dbcode",""))); rec["candidate_key"]=candidate_key(rec); rec["source_file"]=source_file; rows.append(rec)
    return pd.DataFrame(rows)
def read_candidates(paths):
    frames=[]
    for raw in paths:
        p=Path(raw); s=p.suffix.lower()
        if s==".csv": df=pd.read_csv(p,dtype=str,keep_default_na=False)
        elif s in {".xlsx",".xlsm"}: df=pd.read_excel(p,dtype=str,keep_default_na=False)
        elif s==".json":
            obj=json.loads(p.read_text(encoding="utf-8")); obj=obj.get("rows",obj.get("records",obj)) if isinstance(obj,dict) else obj
            if not isinstance(obj,list): raise ValueError(f"无法识别JSON结构: {p.name}")
            df=pd.DataFrame(obj)
        elif s==".xls":
            tables=pd.read_html(p); df=tables[0] if tables else pd.DataFrame()
        else: raise ValueError(f"不支持文件: {p.name}")
        frames.append(_normalise(df,p.name))
    if not frames: return pd.DataFrame(columns=CANON+["candidate_key","source_file"])
    out=pd.concat(frames,ignore_index=True)
    return out.drop_duplicates("candidate_key",keep="first").reset_index(drop=True)
