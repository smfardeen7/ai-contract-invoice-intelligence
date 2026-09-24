"""Airflow 3 Task SDK integration. Requires mounted local filesystem paths."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from airflow.sdk import dag, task


@dag(schedule="@daily", start_date=datetime(2026, 9, 22, tzinfo=timezone.utc),
     catchup=False, tags=["invoices"], max_active_runs=1)
def invoice_pipeline():
    @task(retries=2)
    def ingest_validate_store():
        from invoice_intelligence.batch import run_batch
        return run_batch(
            Path(os.environ.get("INVOICE_INBOX", "/opt/invoices/inbox")),
            Path(os.environ.get("INVOICE_DB", "/opt/invoices/var/invoices.sqlite")),
            json.loads(Path(os.environ.get("INVOICE_CONTRACTS", "/opt/invoices/contracts.json")).read_text()),
        )

    @task
    def check_batch(summary):
        if summary["counts"]["failed"]:
            raise ValueError(f"{summary['counts']['failed']} documents failed extraction; inspect upstream task result")
        return summary["counts"]
    check_batch(ingest_validate_store())


invoice_pipeline()
