from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def index(request):
    """Sampling module UI shell.

    Current package is for local UI/interaction verification. It intentionally
    does not create or mutate sampling database records.
    """
    sample_sets = [
        {
            "name": "法学论文 T2 样本集 v1",
            "project": "法学论文匿名评审基准",
            "version": "v1",
            "status": "draft",
            "status_label": "待冻结",
            "candidate_count": 1287,
            "eligible_count": 1219,
            "review_count": 23,
            "main_count": 45,
            "holdout_count": 15,
            "reserve_count": 30,
            "method": "确定性哈希 + 期号均衡",
            "seed": "law_sampling_v1",
            "fingerprint": "7f492ab394d8c2f1",
            "created_by": request.user.username,
        },
    ]

    candidates = [
        {"title": "数字时代平台治理的法治逻辑", "journal": "中国法学", "year": 2024, "issue": "03", "tier": "T1", "period": "P3", "eligibility": "ELIGIBLE_AUTO"},
        {"title": "人工智能司法应用的规范边界", "journal": "法学研究", "year": 2024, "issue": "05", "tier": "T1", "period": "P3", "eligibility": "UNCERTAIN"},
        {"title": "数据权益保护的制度路径", "journal": "中外法学", "year": 2025, "issue": "01", "tier": "T1", "period": "P3", "eligibility": "ELIGIBLE_AUTO"},
        {"title": "《法学研究》2025年第2期征稿启事", "journal": "法学研究", "year": 2025, "issue": "02", "tier": "T1", "period": "P3", "eligibility": "EXCLUDED_AUTO"},
        {"title": "算法推荐中的平台责任重构", "journal": "法商研究", "year": 2023, "issue": "06", "tier": "T2", "period": "P2", "eligibility": "ELIGIBLE_AUTO"},
        {"title": "生成式人工智能与著作权例外", "journal": "现代法学", "year": 2023, "issue": "04", "tier": "T2", "period": "P2", "eligibility": "UNCERTAIN"},
    ]

    review_items = [
        {"key": "r1", "title": "人工智能司法应用的规范边界", "journal": "法学研究", "year": 2024, "issue": "05", "tier": "T1", "period": "P3"},
        {"key": "r2", "title": "生成式人工智能与著作权例外", "journal": "现代法学", "year": 2023, "issue": "04", "tier": "T2", "period": "P2"},
    ]

    selected = [
        {"paper_id": "P001", "role": "MAIN", "title": "数字时代平台治理的法治逻辑", "journal": "中国法学", "year": 2024, "issue": "03", "tier": "T1", "period": "P3", "rank": 1},
        {"paper_id": "P002", "role": "MAIN", "title": "数据权益保护的制度路径", "journal": "中外法学", "year": 2025, "issue": "01", "tier": "T1", "period": "P3", "rank": 1},
        {"paper_id": "H001", "role": "HOLDOUT", "title": "算法推荐中的平台责任重构", "journal": "法商研究", "year": 2023, "issue": "06", "tier": "T2", "period": "P2", "rank": 1},
        {"paper_id": "R001", "role": "RESERVE", "title": "生成式人工智能与著作权例外", "journal": "现代法学", "year": 2023, "issue": "04", "tier": "T2", "period": "P2", "rank": 2},
    ]

    return render(request, "core/sampling_preview.html", {
        "shell_section": "样本库",
        "sample_sets": sample_sets,
        "active_set": sample_sets[0],
        "candidates": candidates,
        "review_items": review_items,
        "selected": selected,
    })
