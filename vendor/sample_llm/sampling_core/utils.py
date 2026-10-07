from __future__ import annotations
import hashlib, re, unicodedata
from urllib.parse import urlparse, parse_qs

def clean(value) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value)).replace("\xa0", " ")).strip()

def norm(value) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", clean(value).lower())

def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

def stable_hash(seed: str, *parts: str) -> str:
    return sha256_text("|".join([clean(seed), *[clean(p) for p in parts]]))

def normalize_doi(value: str) -> str:
    x = clean(value).lower()
    x = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", x)
    x = re.sub(r"^doi\s*[:：]?\s*", "", x)
    return x.rstrip(".,;；")

def parse_cnki(url: str, filename: str = "", dbcode: str = "") -> dict:
    url, filename, dbcode = clean(url), clean(filename), clean(dbcode)
    if url:
        try:
            qs = parse_qs(urlparse(url).query)
            for k in ("filename","FileName","fileName","FILENAME"):
                if not filename and qs.get(k): filename = clean(qs[k][0])
            for k in ("dbcode","DBCODE","DbCode"):
                if not dbcode and qs.get(k): dbcode = clean(qs[k][0])
        except Exception:
            pass
    if dbcode and filename: key, method = f"{dbcode}:{filename}", "dbcode+filename"
    elif filename: key, method = filename, "filename"
    elif url: key, method = "URL:" + sha256_text(url)[:16], "url_hash"
    else: key, method = "", "missing"
    return {"cnki_dbcode":dbcode,"cnki_filename":filename,"cnki_record_key":key,"record_key_method":method}

def candidate_key(rec: dict) -> str:
    ids = parse_cnki(rec.get("url",""), rec.get("cnki_filename",""), rec.get("cnki_dbcode",""))
    if ids["cnki_record_key"] and ids["record_key_method"] != "url_hash": return "cnki:" + ids["cnki_record_key"].lower()
    doi = normalize_doi(rec.get("doi",""))
    if doi: return "doi:" + doi
    if clean(rec.get("url","")): return "url:" + clean(rec["url"]).lower().rstrip("/")
    author = re.split(r"[;；,，、]", clean(rec.get("authors","")))[0]
    return "meta:" + "|".join([norm(rec.get("title","")), clean(rec.get("year",""))[:4], norm(rec.get("journal","")), norm(author)])
