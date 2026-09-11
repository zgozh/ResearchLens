"""ResearchLens Evaluation harness (Spec §21/§22/§35).

Runs REAL claim extraction (and evidence linking) over the dataset via the AI
client, then aligns the extracted claims against ground truth to compute metrics:
  - Claim Extraction Recall / Precision / F1
  - Evidence Coverage          (matched claims that carry at least one evidence)
  - Unsupported Claim Rate     (extracted claims without evidence → target ≈ 0)
  - Citation Accuracy          (matched claims whose evidence page matches GT)

These are genuine measured numbers, not fabricated (Spec §22 要求必须真测).
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from app.services.claims import extract_claims

SIM_THRESHOLD = 0.30


def _ngrams(text: str, n: int = 2) -> set:
    """中文用**字符 bigram**，拉丁用词 bigram；**不丢中文单字**。

    修复的真实缺陷：旧实现把中文当成一个整 token（``text.split()`` 对中文无效），
    导致中文断言之间几乎零重叠；且 ``text.lower()`` 后又对原文做正则，
    大小写混用使拉丁术语匹配不稳。
    """
    lowered = (text or "").lower()
    cjk = re.findall(r"[\u4e00-\u9fff\u3400-\u4dbf]", lowered)
    latin = re.findall(r"[a-z0-9][a-z0-9._+\-/]*", lowered)

    grams: set = set()
    if len(cjk) >= n:
        grams |= {cjk[i] + cjk[i + 1] for i in range(len(cjk) - 1)}
    else:
        grams |= set(cjk)
    if len(latin) >= n:
        grams |= {f"{a} {b}" for a, b in zip(latin, latin[1:])}
    else:
        grams |= set(latin)
    if not grams:
        grams = {lowered}
    return grams


def _key_tokens(text: str) -> set:
    """Numbers + capitalized/technical tokens — the substantive 'entities' of a claim."""
    toks = re.findall(r"\b[A-Z][A-Za-z]+\b|\b\d+(?:\.\d+)?%?\b|\b[A-Z]+\b", text)
    return set(t.lower() for t in toks)


def _sim(a: str, b: str) -> float:
    """Claim-match score: bigram overlap plus key-token (numbers/entities) overlap.

    LLM phrasing differs from ground-truth, so pure lexical bigram Jaccard under-measures
    paraphrased claims. Weighting shared numbers/entities better reflects semantic coverage.
    """
    a, b = a.lower(), b.lower()
    ga, gb = _ngrams(a), _ngrams(b)
    lex = len(ga & gb) / len(ga | gb) if (ga | gb) else 0.0
    ka, kb = _key_tokens(a), _key_tokens(b)
    ent = len(ka & kb) / len(ka | kb) if (ka | kb) else 0.0
    return round(0.55 * lex + 0.45 * ent, 4)


def _match(extracted: List[Dict], gt: List[Dict]) -> Tuple[List[Optional[int]], List[Optional[int]]]:
    """**一对一**匹配：按相似度降序贪心，每个 gold / 每个 extracted 最多配一次。

    修复的真实缺陷：旧实现 ``gt_match`` 允许**多个 gold 指向同一个 extracted**，
    使 ``covered`` 可被一条万能断言刷高（一对多虚高）。现在两侧都保证唯一。
    """
    pairs: List[Tuple[float, int, int]] = []
    for gi, g in enumerate(gt):
        for ei, e in enumerate(extracted):
            s = _sim(g["statement"], e.get("statement", ""))
            if s >= SIM_THRESHOLD:
                pairs.append((s, gi, ei))
    pairs.sort(key=lambda t: (-t[0], t[1], t[2]))

    gt_match: List[Optional[int]] = [None] * len(gt)
    ext_match: List[Optional[int]] = [None] * len(extracted)
    for _, gi, ei in pairs:
        if gt_match[gi] is not None or ext_match[ei] is not None:
            continue
        gt_match[gi] = ei
        ext_match[ei] = gi
    return gt_match, ext_match


def compute_paper_metrics(paper: Dict, extracted: List[Dict]) -> Dict:
    gt = paper["gt_claims"]
    n_gt, n_ext = len(gt), len(extracted)
    gt_match, ext_match = _match(extracted, gt)

    covered = sum(1 for _ in gt_match if _ is not None)
    matched_ext = [i for i, m in enumerate(ext_match) if m is not None]
    tp = len(matched_ext)

    recall = covered / n_gt if n_gt else 0.0
    precision = tp / n_ext if n_ext else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    # evidence coverage: matched extracted claims with >=1 evidence
    with_ev = [i for i in matched_ext if extracted[i].get("evidence")]
    evidence_coverage = len(with_ev) / len(matched_ext) if matched_ext else 0.0

    # unsupported claim rate: all extracted claims with 0 evidence
    no_ev = [e for e in extracted if not e.get("evidence")]
    unsupported_rate = len(no_ev) / n_ext if n_ext else 0.0

    # citation accuracy: matched + evidence where an evidence page matches GT pages.
    # Only meaningful when both evidence and GT carry page numbers (page-structured PDF input);
    # on a plain-text corpus pages are unverifiable, so report N/A (None) instead of 0.
    cite_ok = 0
    cite_den = 0
    for i in matched_ext:
        e0 = extracted[i]
        evs = e0.get("evidence") or []
        if not evs:
            continue
        gt_pages = [p for p in gt[ext_match[i]]["evidence_pages"] if p]
        got_pages = [
            e.get("page") for e in evs
            if e.get("page") is not None and str(e.get("page")).strip().isdigit()
        ]
        if not gt_pages or not got_pages:
            continue
        cite_den += 1
        if any(int(p) in {int(x) for x in gt_pages} for p in got_pages):
            cite_ok += 1
    # 注意：此处已是 **percent**（0..100）。旧实现又在返回时 ×100，
    # 使最大可报值变成 10000；且 cite_den==0 时 None×100 直接崩溃。
    citation_accuracy = round(cite_ok / cite_den * 100, 1) if cite_den else None

    return {
        "paper": paper["id"],
        "title": paper["title"],
        "n_gt": n_gt,
        "n_extracted": n_ext,
        "covered": covered,
        "recall": round(recall * 100, 1),
        "precision": round(precision * 100, 1),
        "f1": round(f1 * 100, 1),
        "evidence_coverage": round(evidence_coverage * 100, 1),
        "unsupported_claim_rate": round(unsupported_rate * 100, 1),
        # 已是 percent：**不再缩放**（旧代码 round(citation_accuracy * 100, 1)
        # 是双重缩放，且 None 时会 TypeError）
        "citation_accuracy": citation_accuracy,
        "grounded_claims": len(with_ev),
    }


def run_benchmark(ai, papers: List[Dict]) -> Dict:
    per_paper = []
    for p in papers:
        extracted = extract_claims(ai, p["text"], {})
        per_paper.append(compute_paper_metrics(p, extracted))

    agg = _aggregate(per_paper)
    return {"papers": per_paper, "aggregate": agg}


def _aggregate(items: List[Dict]) -> Dict:
    if not items:
        return {}
    n_gt = sum(x["n_gt"] for x in items)
    n_ext = sum(x["n_extracted"] for x in items)
    covered = sum(x["covered"] for x in items)
    # 一对一匹配后，covered 即真正的 TP（一个 gold 只对应一个 extracted）
    tp = covered
    recall = tp / n_gt if n_gt else 0.0
    precision = tp / n_ext if n_ext else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    # 量纲统一：per-paper 的 unsupported_claim_rate 已是 percent，
    # 用 n_extracted 加权还原到全局比例（旧实现混用了 ratio 与 percent）。
    if n_ext:
        unsupported_num = sum(
            (x["unsupported_claim_rate"] / 100.0) * x["n_extracted"] for x in items
        )
        unsupported = unsupported_num / n_ext * 100.0
    else:
        unsupported = 0.0
    cite = [x["citation_accuracy"] for x in items if x.get("citation_accuracy") is not None]
    ev_cov = sum(x["evidence_coverage"] for x in items) / len(items)
    return {
        "papers": len(items),
        "claims": n_gt,
        "extracted": n_ext,
        "claim_extraction_recall": round(recall * 100, 1),
        "claim_extraction_precision": round(precision * 100, 1),
        "claim_extraction_f1": round(f1 * 100, 1),
        "evidence_coverage": round(ev_cov, 1),
        "citation_accuracy": round(sum(cite) / len(cite), 1) if cite else "N/A",
        "unsupported_claim_rate": round(unsupported, 1),
    }
