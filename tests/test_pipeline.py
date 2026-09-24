from decimal import Decimal
import json
import sqlite3

import pytest

from invoice_intelligence.pipeline import extract_invoice, validate_invoice, ingest


TEXT = '''Invoice: INV-001
Vendor: Northwind Labs
Contract: C-100
Date: 2026-09-01
Due Date: 2026-10-01
Currency: USD
Description | Quantity | Unit Price
Analysis | 2 | 125.00
Storage | 1 | 50.00
Subtotal: 300.00
Tax: 24.00
Total: 324.00
'''
CONTRACT = {"contract_id": "C-100", "vendor": "Northwind Labs", "currency": "USD", "maximum_total": "500", "tax_rate": "0.08", "payment_days": 30, "rates": {"Analysis": "125", "Storage": "50"}}


def test_extract_decimal_amounts_and_fields():
    result = extract_invoice(TEXT)
    assert result.invoice_id == "INV-001"
    assert result.total == Decimal("324.00")
    assert sum(i.quantity * i.unit_price for i in result.items) == Decimal("300")
    assert validate_invoice(result, CONTRACT) == []


def test_bad_totals_and_unapproved_rates_are_reviewed():
    result = extract_invoice(TEXT.replace("Total: 324.00", "Total: 325.00").replace("2 | 125.00", "2 | 126.00"))
    codes = {issue["code"] for issue in validate_invoice(result, CONTRACT)}
    assert {"line_sum_mismatch", "total_mismatch", "rate_exceeded"} <= codes


@pytest.mark.parametrize("text", ["", TEXT.replace("Currency: USD", "Currency: DOGE"), TEXT.replace("Date: 2026-09-01", "Date: yesterday"), TEXT.replace("Total: 324.00", "Total: NaN"), TEXT.replace("2 | 125.00", "-2 | 125.00")])
def test_reject_invalid_documents(text):
    with pytest.raises(ValueError):
        extract_invoice(text)


def test_pipeline_is_idempotent_and_preserves_review_findings(tmp_path):
    source = tmp_path / "invoice.txt"
    source.write_text(TEXT)
    db = tmp_path / "invoices.db"
    first = ingest(source, db, CONTRACT)
    second = ingest(source, db, CONTRACT)
    assert first["status"] == "accepted"
    assert second["duplicate"] is True
    assert first["document_id"] == second["document_id"]
    with sqlite3.connect(db) as connection:
        assert connection.execute("select count(*) from documents").fetchone()[0] == 1


def test_changed_invoice_with_same_business_key_is_flagged(tmp_path):
    source = tmp_path / "invoice.txt"
    source.write_text(TEXT)
    db = tmp_path / "invoices.db"
    ingest(source, db, CONTRACT)
    source.write_text(TEXT.replace("324.00", "326.00"))
    result = ingest(source, db, CONTRACT)
    assert "duplicate_invoice_id" in {x["code"] for x in result["issues"]}
    assert result["status"] == "needs_review"


def test_missing_contract_requires_review():
    assert "contract_missing" in {x["code"] for x in validate_invoice(extract_invoice(TEXT), None)}


def test_pdf_ingestion(tmp_path):
    from reportlab.pdfgen.canvas import Canvas
    p = tmp_path / "invoice.pdf"
    c = Canvas(str(p))
    t = c.beginText(50, 780)
    for line in TEXT.splitlines():
        t.textLine(line)
    c.drawText(t)
    c.save()
    result = ingest(p, tmp_path / "db.sqlite", CONTRACT)
    assert result["invoice"]["total"] == "324.00"


def test_web_validation_and_review_list(tmp_path):
    from invoice_intelligence.web import create_app
    client = create_app(tmp_path / "db.sqlite", {"C-100": CONTRACT}).test_client()
    assert client.get("/").status_code == 200
    assert client.post("/api/invoices", json={"text": "bad"}).status_code == 422
    response = client.post("/api/invoices", json={"text": TEXT})
    assert response.status_code == 201
    assert response.json["status"] == "accepted"
    assert len(client.get("/api/invoices").json) == 1


def test_batch_reports_failure_without_losing_valid_invoice(tmp_path):
    from invoice_intelligence.batch import run_batch
    (tmp_path / "a.txt").write_text(TEXT)
    (tmp_path / "b.txt").write_text("broken invoice")
    result = run_batch(tmp_path, tmp_path / "db.sqlite", {"C-100": CONTRACT})
    assert result["counts"] == {"accepted": 1, "needs_review": 0, "failed": 1}


def test_policy_change_revalidates_identical_document(tmp_path):
    source = tmp_path / "a.txt"
    source.write_text(TEXT)
    ingest(source, tmp_path / "db.sqlite", CONTRACT)
    result = ingest(source, tmp_path / "db.sqlite", {**CONTRACT, "maximum_total": "100"})
    assert result["duplicate"] is False
    assert {i["code"] for i in result["issues"]} == {"contract_limit_exceeded"}


def test_whitespace_only_change_is_same_document(tmp_path):
    from invoice_intelligence.pipeline import ingest_text
    original = ingest_text(TEXT, tmp_path / "db.sqlite", CONTRACT)
    result = ingest_text("\n" + TEXT.rstrip() + "\n\n", tmp_path / "db.sqlite", CONTRACT)
    assert result["duplicate"] is True
    assert result["document_id"] == original["document_id"]


def test_large_line_totals_produce_review_instead_of_decimal_overflow():
    text = TEXT.replace("Analysis | 2 | 125.00", "\n".join(["Analysis | 1000000000000 | 1000000000000"] * 100))
    issues = validate_invoice(extract_invoice(text), CONTRACT)
    assert "line_sum_mismatch" in {i["code"] for i in issues}


def test_batch_error_metadata_excludes_raw_invoice_values(tmp_path):
    from invoice_intelligence.batch import run_batch
    (tmp_path / "bad.txt").write_text(TEXT.replace("2 | 125.00", "PRIVATE-QUANTITY-MARKER | 125.00"))
    result = run_batch(tmp_path, tmp_path / "db.sqlite", {"C-100": CONTRACT})
    assert result["counts"]["failed"] == 1
    assert "PRIVATE-QUANTITY-MARKER" not in json.dumps(result)
