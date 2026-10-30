"""C5 推荐/摘要离线校准。

用法：
    python scripts/calibrate_c5.py --dataset tests/fixtures/c5_cases.json
"""

import argparse
import json
import statistics
from pathlib import Path

from app.core.config import get_settings
from app.domain.profile.proactive import _rule_suggestions, normalize_suggestions


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="tests/fixtures/c5_cases.json")
    args = parser.parse_args()
    cases = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    settings = get_settings()

    item_lengths: list[int] = []
    summary_lengths: list[int] = []
    counts: list[int] = []
    duplicates = 0
    keyword_total = 0
    keyword_hits = 0

    for case in cases:
        result = _rule_suggestions(
            case.get("tags") or [],
            case.get("matters") or [],
            max_items=settings.suggestion_max_items,
            max_chars=settings.suggestion_item_max_chars,
        )
        suggestions = normalize_suggestions(
            result["suggestions"],
            max_items=settings.suggestion_max_items,
            max_chars=settings.suggestion_item_max_chars,
        )
        summary = result["summary"][: settings.suggestion_summary_max_chars]
        counts.append(len(suggestions))
        item_lengths.extend(len(item) for item in suggestions)
        summary_lengths.append(len(summary))
        duplicates += len(result["suggestions"]) - len(set(result["suggestions"]))
        expected = case.get("expected_keywords") or []
        if expected:
            keyword_total += 1
            text = " ".join(suggestions + [summary])
            if any(word in text for word in expected):
                keyword_hits += 1

    print(
        json.dumps(
            {
                "cases": len(cases),
                "avgSuggestionsPerCase": round(statistics.mean(counts), 2) if counts else 0,
                "maxSuggestionsPerCase": max(counts) if counts else 0,
                "maxItemChars": max(item_lengths) if item_lengths else 0,
                "avgSummaryChars": round(statistics.mean(summary_lengths), 1)
                if summary_lengths
                else 0,
                "duplicateSuggestions": duplicates,
                "keywordHitRate": round(keyword_hits / keyword_total, 4)
                if keyword_total
                else None,
                "limits": {
                    "maxItems": settings.suggestion_max_items,
                    "itemChars": settings.suggestion_item_max_chars,
                    "summaryChars": settings.suggestion_summary_max_chars,
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
