"""Summarize real page-split issues from page_split_audit.json."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

REAL_TYPES = {
    "partial_asin",
    "partial_hsn",
    "partial_gstin_in_ean",
    "possible_unmerged_tail",
    "qty_mismatch",
    "gstin_in_ean",
}

data = json.loads(
    (Path(__file__).resolve().parent.parent / "data" / "page_split_audit.json").read_text(encoding="utf-8")
)

real_docs = []
for row in data["flagged"]:
    real = [i for i in row["issues"] if i["type"] in REAL_TYPES]
    if real:
        real_docs.append({**row, "issues": real})

by_type: dict[str, int] = defaultdict(int)
for row in real_docs:
    for issue in row["issues"]:
        by_type[issue["type"]] += 1

print("=== SUMMARY ===")
print(f"Total documents:        {data['total_documents']}")
print(f"All are multi-page:     {data['multi_page_documents']}")
print(f"REAL split/data issues: {len(real_docs)}")
print(f"Clean (no real issue):  {data['total_documents'] - len(real_docs)}")
print()
print("By real issue type:")
for t, c in sorted(by_type.items(), key=lambda x: -x[1]):
    print(f"  {t}: {c}")

print(f"\n=== ALL {len(real_docs)} DOCUMENTS WITH REAL SPLIT / DATA ISSUES ===\n")
for row in sorted(real_docs, key=lambda x: x["file_name"]):
    print(f"{row['file_name']}")
    print(f"  {row['source']} | {row['subtype']} | pages={row['pages']} | items={row['item_count']}")
    for issue in row["issues"]:
        print(f"  - Item {issue['item']} [{issue['type']}] {issue['field']} = {issue['value']!r} (page {issue['page']})")
        if issue.get("product_snippet"):
            print(f"    text: {issue['product_snippet'][:75]!r}")
    print()

real_files = {r["file_name"] for r in real_docs}
all_flagged = {r["file_name"] for r in data["flagged"]}
footer_only = len(all_flagged - real_files)
print(f"=== {footer_only} docs flagged only for page-2 footer text (tax words / E&OE) — data OK ===")

clean = data["total_documents"] - len(real_files)
print(f"\n=== {clean} docs with NO real split issues ===")
