"""统一时期、期刊层级及范围校验；固定研究 registry 不是演示数据。"""
import json
from pathlib import Path

REGISTRY = json.loads((Path(__file__).parent / 'config/journal_registry.json').read_text(encoding='utf-8'))
PERIOD_MAP = {p['id']: p for p in REGISTRY['periods']}
JOURNALS = sorted({j for js in REGISTRY['tiers'].values() for j in js})
BASE_TIERS = {j: t for t, js in REGISTRY['tiers'].items() for j in js}


def tier_for(journal, period_id):
    return REGISTRY.get('period_tier_overrides', {}).get(journal, {}).get(period_id, BASE_TIERS.get(journal))


def journal_tiers(journal, period_ids, holdout=False):
    ids = list(period_ids) + (['P3'] if holdout else [])
    return {tier_for(journal, pid) for pid in ids or PERIOD_MAP}


def validate_scope(run):
    errors = {}
    periods = run.periods if isinstance(run.periods, list) else []
    valid = [p for p in periods if isinstance(p, dict) and p.get('id') in PERIOD_MAP
             and p.get('start_year') == PERIOD_MAP[p['id']]['start_year']
             and p.get('end_year') == PERIOD_MAP[p['id']]['end_year']]
    if not periods:
        errors['periods'] = '请至少选择一个研究时期'
    elif len(valid) != len(periods) or len({p['id'] for p in valid}) != len(periods):
        errors['periods'] = '研究时期无效，请重新选择'
    tiers = run.selected_tiers if isinstance(run.selected_tiers, list) else []
    if not tiers:
        errors['selected_tiers'] = '请至少选择一个期刊层级'
    elif any(t not in REGISTRY['tiers'] for t in tiers):
        errors['selected_tiers'] = '期刊层级无效'
    journals = run.selected_journals if isinstance(run.selected_journals, list) else []
    if not journals:
        errors['selected_journals'] = '请至少选择一本期刊'
    elif any(j not in JOURNALS for j in journals):
        errors['selected_journals'] = '期刊不在研究期刊目录中'
    elif valid and tiers and any(not (journal_tiers(j, [p['id'] for p in valid], run.holdout_enabled) & set(tiers)) for j in journals):
        errors['selected_journals'] = '所选期刊与当前时期、层级不匹配，请重新选择'
    if run.main_n is not None and not 1 <= run.main_n <= 32767:
        errors['main_n'] = '主样本数须为 1–32767 的整数'
    if run.reserve_n is not None and not 0 <= run.reserve_n <= 32767:
        errors['reserve_n'] = '备用数须为 0–32767 的整数'
    if run.holdout_enabled:
        for field in ('holdout_start', 'holdout_end'):
            v = getattr(run, field)
            if v is None:
                errors[field] = '启用留出样本时请填写年份'
            elif not 1900 <= v <= 2100:
                errors[field] = '年份须在 1900–2100 之间'
        if run.holdout_n is None or not 1 <= run.holdout_n <= 32767:
            errors['holdout_n'] = '请填写大于 0 的留出样本数'
        if not any(f in errors for f in ('holdout_start', 'holdout_end')):
            if run.holdout_start > run.holdout_end:
                errors['holdout_end'] = '结束年份不能早于开始年份'
            elif any(not (run.holdout_end < p['start_year'] or run.holdout_start > p['end_year']) for p in valid):
                errors['holdout_start'] = '留出期不能与主研究时期重叠'
    return errors
