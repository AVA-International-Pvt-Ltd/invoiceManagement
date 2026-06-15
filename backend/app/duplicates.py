"""Detect duplicate uploads by file content hash and file name."""
from __future__ import annotations

import hashlib
from collections import defaultdict
from pathlib import Path
from typing import Any

from .models import JobResult


def content_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def hash_file_path(path: Path) -> str | None:
    if not path.is_file():
        return None
    return content_hash(path.read_bytes())


def _job_upload_entry(job_id: str, job: JobResult) -> dict[str, Any] | None:
    if not job.document:
        return None
    audit = job.document.audit or {}
    header = job.document.header or {}
    file_hash = audit.get("content_hash") or ""
    if not file_hash:
        source_uri = audit.get("source_uri") or ""
        if source_uri:
            computed = hash_file_path(Path(source_uri))
            if computed:
                file_hash = computed
    return {
        "job_id": job_id,
        "file_name": audit.get("file_name") or "",
        "uploaded_at": audit.get("saved_at") or "",
        "content_hash": file_hash,
        "invoice_number": header.get("invoice_number") or header.get("document_number") or "",
        "vendor": (job.document.vendor.name or job.document.vendor.gstin or ""),
    }


def find_prior_upload(
    jobs: dict[str, JobResult],
    *,
    file_hash: str,
    file_name: str,
    exclude_job_id: str | None = None,
) -> dict[str, Any] | None:
    """Return info about an earlier upload of the same file, if any."""
    same_hash: list[dict[str, Any]] = []
    same_name: list[dict[str, Any]] = []

    for job_id, job in jobs.items():
        if exclude_job_id and job_id == exclude_job_id:
            continue
        entry = _job_upload_entry(job_id, job)
        if not entry:
            continue
        if file_hash and entry["content_hash"] == file_hash:
            same_hash.append(entry)
        if file_name and entry["file_name"].lower() == file_name.lower():
            same_name.append(entry)

    if same_hash:
        same_hash.sort(key=lambda item: item["uploaded_at"])
        first = same_hash[0]
        return {
            "match_type": "exact",
            "first_job_id": first["job_id"],
            "first_uploaded_at": first["uploaded_at"],
            "prior_count": len(same_hash),
            "upload_number": len(same_hash) + 1,
        }

    if same_name:
        same_name.sort(key=lambda item: item["uploaded_at"])
        first = same_name[0]
        return {
            "match_type": "filename",
            "first_job_id": first["job_id"],
            "first_uploaded_at": first["uploaded_at"],
            "prior_count": len(same_name),
            "upload_number": len(same_name) + 1,
        }

    return None


def scan_duplicates(jobs: dict[str, JobResult]) -> dict[str, Any]:
    """Group all duplicate uploads across stored jobs."""
    by_hash: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    entries: list[dict[str, Any]] = []

    for job_id, job in jobs.items():
        entry = _job_upload_entry(job_id, job)
        if not entry:
            continue
        entries.append(entry)
        if entry["content_hash"]:
            by_hash[entry["content_hash"]].append(entry)
        name_key = entry["file_name"].lower().strip()
        if name_key:
            by_name[name_key].append(entry)

    exact_groups: list[dict[str, Any]] = []
    for file_hash, group in by_hash.items():
        if len(group) < 2:
            continue
        group.sort(key=lambda item: item["uploaded_at"])
        exact_groups.append(
            {
                "match_type": "exact",
                "content_hash": file_hash,
                "file_name": group[0]["file_name"],
                "count": len(group),
                "uploads": [
                    {**item, "upload_number": index + 1}
                    for index, item in enumerate(group)
                ],
            }
        )

    name_groups: list[dict[str, Any]] = []
    for name_key, group in by_name.items():
        if len(group) < 2:
            continue
        hashes = {item["content_hash"] for item in group if item["content_hash"]}
        if len(hashes) <= 1 and len(hashes) == 1:
            continue
        group.sort(key=lambda item: item["uploaded_at"])
        name_groups.append(
            {
                "match_type": "filename",
                "file_name": group[0]["file_name"],
                "count": len(group),
                "uploads": [
                    {**item, "upload_number": index + 1}
                    for index, item in enumerate(group)
                ],
            }
        )

    duplicate_job_ids: set[str] = set()
    for group in exact_groups + name_groups:
        for upload in group["uploads"][1:]:
            duplicate_job_ids.add(upload["job_id"])

    return {
        "total_documents": len(entries),
        "duplicate_file_count": len(duplicate_job_ids),
        "duplicate_group_count": len(exact_groups) + len(name_groups),
        "duplicate_job_ids": sorted(duplicate_job_ids),
        "exact_duplicate_groups": exact_groups,
        "filename_duplicate_groups": name_groups,
    }
