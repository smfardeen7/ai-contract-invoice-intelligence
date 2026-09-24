"""Batch entrypoint shared by the CLI and optional Airflow scheduler."""
from pathlib import Path
from .pipeline import extract_invoice, read_document, ingest_text


def run_batch(inbox: Path, db_path: Path, contracts: dict):
    results = []
    counts = {"accepted": 0, "needs_review": 0, "failed": 0}
    for path in sorted(Path(inbox).iterdir()):
        if not path.is_file() or path.suffix.lower() not in {".txt", ".pdf"}:
            continue
        try:
            text = read_document(path)
            invoice = extract_invoice(text)
            result = ingest_text(text, db_path, contracts.get(invoice.contract_id))
            # Keep raw invoice data out of scheduler metadata/logs.
            row = {"document_id": result["document_id"], "status": result["status"], "duplicate": result["duplicate"]}
        except (ValueError, OSError):
            row = {"source": path.name, "status": "failed", "error_code": "invalid_or_unreadable_document",
                   "error": "Inspect the source locally with the ingest CLI; invoice values are omitted from scheduler metadata"}
        counts[row["status"]] += 1
        results.append(row)
    return {"counts": counts, "documents": results}
