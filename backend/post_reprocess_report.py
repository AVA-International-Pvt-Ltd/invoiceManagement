"""Post-reprocess quality report."""
from collections import Counter

from app.extraction_quality import scan_all_documents
from app.job_summary import build_job_summary
from app.models import JobResult
from app.storage import load_all_extractions


def main() -> None:
    jobs = {jid: JobResult.model_validate(p) for jid, p in load_all_extractions().items()}
    summary = scan_all_documents(jobs)

    st_counts: Counter[str] = Counter()
    dq_counts: Counter[str] = Counter()
    verified_not_100: list[str] = []

    for jid, job in jobs.items():
        s = build_job_summary(jid, job)
        st = s.get("extraction_status") or "unknown"
        dq = s.get("data_quality") or "0%"
        st_counts[st] += 1
        dq_counts[dq] += 1
        if st == "verified" and dq != "100%":
            verified_not_100.append(f"{s.get('file_name', jid)} -> {dq}")

    print("=== REPROCESS QUALITY REPORT ===")
    print(f"Total documents:  {len(jobs)}")
    print(f"Verified:         {st_counts.get('verified', 0)}")
    print(f"Review suggested: {st_counts.get('needs_review', 0)}")
    print(f"Failed:           {st_counts.get('failed', 0)}")
    print(f"Verified + 100%:  {st_counts.get('verified', 0) - len(verified_not_100)}")
    print()
    print("By extraction status:", dict(st_counts))
    print("By data quality:", dict(dq_counts))

    if verified_not_100:
        print("\nVerified but not 100% (should be 0):")
        for row in verified_not_100:
            print(f"  {row}")

    if summary["not_verified"]:
        print(f"\n=== {len(summary['not_verified'])} DOCS NEED ATTENTION ===")
        for doc in summary["not_verified"]:
            print(f"  [{doc['status']}] {doc['file_name']}")
            for issue in doc.get("issues", [])[:2]:
                print(f"      - {issue}")


if __name__ == "__main__":
    main()
