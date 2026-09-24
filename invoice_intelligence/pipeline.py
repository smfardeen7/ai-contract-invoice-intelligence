"""Auditable text extraction, exact currency arithmetic and idempotent storage.

The default extractor deliberately supports a documented invoice text grammar.
It never silently invents missing values or treats extraction as validated payment.
"""
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import json
from pathlib import Path
import re
import sqlite3


@dataclass(frozen=True)
class Item:
    description: str
    quantity: Decimal
    unit_price: Decimal


@dataclass(frozen=True)
class Invoice:
    invoice_id: str
    vendor: str
    contract_id: str
    issued: date
    due: date
    currency: str
    items: tuple[Item, ...]
    subtotal: Decimal
    tax: Decimal
    total: Decimal

    def to_dict(self):
        return json.loads(json.dumps(asdict(self), default=str))


def amount(value: str) -> Decimal:
    if not re.fullmatch(r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?", str(value).strip()):
        raise ValueError(f"Invalid nonnegative decimal amount: {value!r}")
    number = Decimal(str(value).replace(",", "").strip())
    if number > Decimal("1000000000000"):
        raise ValueError("Amount exceeds supported range")
    return number


def extract_invoice(text: str) -> Invoice:
    if not isinstance(text, str) or len(text) > 100000:
        raise ValueError("Invoice text must be at most 100,000 characters")
    fields = {}
    items = []
    allowed = {"invoice", "vendor", "contract", "date", "due date", "currency", "subtotal", "tax", "total"}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if "|" in line:
            parts = [p.strip() for p in line.split("|")]
            if parts == ["Description", "Quantity", "Unit Price"]:
                continue
            if len(parts) != 3 or not parts[0]:
                raise ValueError("Line items must use Description | Quantity | Unit Price")
            quantity, price = amount(parts[1]), amount(parts[2])
            if quantity <= 0:
                raise ValueError("Quantity must be positive")
            items.append(Item(parts[0], quantity, price))
        elif ":" in line:
            key, value = line.split(":", 1)
            key = key.casefold().strip()
            if key in allowed:
                if key in fields:
                    raise ValueError(f"Ambiguous duplicate field: {key}")
                fields[key] = value.strip()
    missing = sorted(allowed - fields.keys())
    if missing or any(not value for value in fields.values()):
        raise ValueError("Required fields missing or empty: " + ", ".join(missing))
    if fields["currency"] not in {"USD", "EUR", "GBP", "INR", "CAD", "AUD"}:
        raise ValueError("Unsupported currency; use a supported ISO currency code")
    if not items:
        raise ValueError("No line items extracted; manual review required")
    return Invoice(fields["invoice"], fields["vendor"], fields["contract"],
                   date.fromisoformat(fields["date"]), date.fromisoformat(fields["due date"]),
                   fields["currency"], tuple(items), amount(fields["subtotal"]),
                   amount(fields["tax"]), amount(fields["total"]))


def validate_invoice(invoice: Invoice, contract: dict | None) -> list[dict]:
    issues = []
    def flag(code, message):
        issues.append({"code": code, "message": message})
    # Precision covers the maximum allowed quantities/prices and bounded document
    # size, so an inconsistent large input is reviewed instead of overflowing.
    with localcontext() as context:
        context.prec = 64
        line_total = sum((i.quantity * i.unit_price for i in invoice.items), Decimal("0")).quantize(Decimal("0.01"))
    if line_total != invoice.subtotal:
        flag("line_sum_mismatch", f"Line items sum to {line_total}; declared subtotal is {invoice.subtotal}")
    if invoice.subtotal + invoice.tax != invoice.total:
        flag("total_mismatch", "Subtotal plus tax differs from the total")
    if invoice.due < invoice.issued:
        flag("due_before_issue", "Due date precedes invoice date")
    if contract is None:
        flag("contract_missing", "No matching contract supplied")
        return issues
    for field, actual in [("contract_id", invoice.contract_id), ("vendor", invoice.vendor), ("currency", invoice.currency)]:
        if actual != contract.get(field):
            flag(field + "_mismatch", f"{field} does not match the supplied contract")
    if "maximum_total" in contract and invoice.total > amount(contract["maximum_total"]):
        flag("contract_limit_exceeded", "Invoice total exceeds the per-invoice contract cap")
    if "tax_rate" in contract:
        try:
            rate = Decimal(str(contract["tax_rate"]))
            if not rate.is_finite() or not 0 <= rate <= 1:
                raise ValueError("Tax rate must be between zero and one")
        except InvalidOperation as exc:
            raise ValueError("Invalid contract tax rate") from exc
        expected_tax = (invoice.subtotal * rate).quantize(Decimal("0.01"))
        if expected_tax != invoice.tax:
            flag("tax_mismatch", f"Expected tax {expected_tax}; declared tax {invoice.tax}")
    if "payment_days" in contract and (invoice.due - invoice.issued).days != int(contract["payment_days"]):
        flag("payment_terms_mismatch", "Payment deadline differs from contract terms")
    rates = contract.get("rates", {})
    for item in invoice.items:
        if item.description not in rates:
            flag("unknown_service", f"Service not in contract: {item.description}")
        elif item.unit_price > amount(rates[item.description]):
            flag("rate_exceeded", f"Rate exceeds contract for {item.description}")
    return issues


def read_document(path: Path) -> str:
    path = Path(path)
    if path.stat().st_size > 5_000_000:
        raise ValueError("Documents are limited to 5 MB")
    if path.suffix.lower() == ".txt":
        return path.read_text(encoding="utf-8")
    if path.suffix.lower() != ".pdf":
        raise ValueError("Only UTF-8 .txt and text-based .pdf files are supported")
    from pypdf import PdfReader
    try:
        reader = PdfReader(path)
        if reader.is_encrypted or len(reader.pages) > 20:
            raise ValueError("PDF must be unencrypted and at most 20 pages")
        text = "\n".join(p.extract_text() or "" for p in reader.pages)
    except Exception as exc:
        raise ValueError("Unable to extract PDF; verify it is a valid text-based PDF") from exc
    if not text.strip():
        raise ValueError("No PDF text found; scanned PDFs require an external OCR step")
    return text


def connect(db_path: Path):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute('''CREATE TABLE IF NOT EXISTS documents (
        document_id TEXT PRIMARY KEY, content_hash TEXT NOT NULL, policy_hash TEXT NOT NULL,
        invoice_id TEXT NOT NULL, vendor TEXT NOT NULL, status TEXT NOT NULL,
        invoice_json TEXT NOT NULL, issues_json TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
    return connection


def ingest_text(text: str, db_path: Path, contract: dict | None):
    invoice = extract_invoice(text)
    # Hash extracted meaning, not PDF whitespace or a textarea's trailing newline.
    canonical = json.dumps(asdict(invoice), sort_keys=True,
                           default=lambda value: str(value.normalize()) if isinstance(value, Decimal) else str(value))
    content_hash = hashlib.sha256(canonical.encode()).hexdigest()
    policy_hash = hashlib.sha256(json.dumps(contract, sort_keys=True).encode()).hexdigest()
    document_id = hashlib.sha256((content_hash + policy_hash).encode()).hexdigest()
    with connect(db_path) as connection:
        # Serialize duplicate checks and writes, including concurrent workers.
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute("SELECT * FROM documents WHERE document_id=?", (document_id,)).fetchone()
        if existing:
            return {"document_id": document_id, "status": existing["status"], "invoice": json.loads(existing["invoice_json"]), "issues": json.loads(existing["issues_json"]), "duplicate": True}
        issues = validate_invoice(invoice, contract)
        previous = connection.execute("SELECT 1 FROM documents WHERE vendor=? AND invoice_id=? AND content_hash<>?", (invoice.vendor, invoice.invoice_id, content_hash)).fetchone()
        if previous:
            issues.append({"code": "duplicate_invoice_id", "message": "Another document has the same vendor and invoice identifier"})
        status = "needs_review" if issues else "accepted"
        connection.execute("INSERT INTO documents(document_id,content_hash,policy_hash,invoice_id,vendor,status,invoice_json,issues_json) VALUES (?,?,?,?,?,?,?,?)",
                           (document_id, content_hash, policy_hash, invoice.invoice_id, invoice.vendor, status, json.dumps(invoice.to_dict()), json.dumps(issues)))
    return {"document_id": document_id, "status": status, "invoice": invoice.to_dict(), "issues": issues, "duplicate": False}


def ingest(path: Path, db_path: Path, contract: dict | None):
    return ingest_text(read_document(Path(path)), db_path, contract)


def list_documents(db_path):
    with connect(db_path) as connection:
        rows = connection.execute("SELECT document_id,status,invoice_json,issues_json,created_at FROM documents ORDER BY created_at DESC,rowid DESC LIMIT 500").fetchall()
    return [{"document_id": r["document_id"], "status": r["status"], "invoice": json.loads(r["invoice_json"]), "issues": json.loads(r["issues_json"]), "created_at": r["created_at"]} for r in rows]
