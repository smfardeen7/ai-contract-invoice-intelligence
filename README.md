# AI Contract Invoice Intelligence

A runnable document-processing application that extracts invoice fields, checks them against contract terms, and stores an auditable review queue. Includes a local web interface, text/PDF ingestion, idempotent batch processing and an optional Apache Airflow DAG.

## Quick start

Python 3.12 is recommended. From this repository:

```sh
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest -q
python -m invoice_intelligence ingest examples/invoice-valid.txt examples/invoice-review.txt
python -m invoice_intelligence serve
```

Open http://127.0.0.1:8050. The first sample passes its contract checks; the second shows a rate mismatch, incorrect total, and wrong payment terms. Submit either twice to see duplicate handling. Reset the demo by choosing a new `--db` path.

```sh
python -m invoice_intelligence list --db var/invoices.sqlite
python -m invoice_intelligence ingest /path/to/invoice.pdf --contracts examples/contracts.json
```

Only text-based PDFs (up to 20 pages, 5 MB) and UTF-8 text are accepted. Scanned PDFs require an external OCR step. Use the field labels and pipe-delimited line-item format in `examples/`; this is an explicit grammar, not a universal invoice parser.

## Architecture

`read_document` → `extract_invoice` → `validate_invoice` → SQLite transaction → review queue.

- Exact decimal arithmetic checks line sums, subtotal/tax/total, contract currency/vendor/identifier, maximum invoice value, item rates, and payment deadline.
- Content and policy hashes provide idempotency while allowing revalidation after a policy change. Conflicting documents with the same vendor/invoice identifier are flagged.
- Each stored record includes normalized data, issue codes and creation time. Source text is not stored.
- Invalid documents fail explicitly; valid extraction with failed business checks enters `needs_review`. “Accepted” means these configured checks passed, not that payment is authorized.
- UI inserts untrusted invoice strings as text, JSON requests have bounded size, SQL is parameterized, and the local CLI binds loopback.

`GET /health`, `GET /api/invoices`, and `POST /api/invoices` (`{"text":"..."}`) are available. The review API returns the latest 500 documents. This local demo has no login: do not expose it publicly or supply confidential financial data without adding authentication, retention controls and a production database.

## Optional orchestration

`dags/invoice_pipeline.py` uses the [Airflow 3 Task SDK](https://airflow.apache.org/docs/task-sdk/stable/examples.html). Install this package's dependencies and make the repository importable on each worker, copy the DAG into the Airflow DAG folder, and set `INVOICE_INBOX`, `INVOICE_DB`, and `INVOICE_CONTRACTS` to mounted absolute paths. One daily run ingests the inbox, validates/stores each document and fails the final check if any input could not be extracted. Identical successful inputs are safe to retry. SQLite is suitable for this local example; distributed workers need shared paths or a replacement database. The batch function is covered by tests; an Airflow scheduler deployment has not been exercised.

## Optional TensorFlow line classification

The deterministic extractor is the default. An independent TensorFlow training experiment is included in `invoice_intelligence/train_tagger.py`; it is not silently used as an extraction model.

```sh
pip install -r requirements-ml.txt
python -m invoice_intelligence.train_tagger /path/to/labeled-lines.csv --output models/line-tagger.keras
```

Supply consented/licensed CSV data with `document_id,text,label` columns, at least five independent documents and two labels. The vocabulary is fitted only on training documents, and the test documents stay separate. The script saves a Keras model, labels and measured report. It uses [TensorFlow TextVectorization](https://www.tensorflow.org/api_docs/python/tf/keras/layers/TextVectorization). No pretrained weights or real training data are bundled. Training, saving, reloading and inference passed a TensorFlow 2.21 smoke test using invented line labels; that test checks execution rather than real extraction quality.

## Docker

```sh
docker build -t invoice-intelligence .
docker run --rm -p 127.0.0.1:8050:8050 invoice-intelligence
```

The container runs as a non-root user. Its database is ephemeral unless you mount a writable `/app/var` volume. Docker configuration is provided; local Python tests are the executed verification.

## Provenance and limits

This original portfolio implementation was developed on **September 22–24, 2026**, based on an earlier invoice-intelligence project concept. Commit timestamps reflect actual work on this version.

All bundled examples are invented. Tests demonstrate the documented behaviors on fixtures, not real-world extraction accuracy or production-scale throughput. Cloud deployment and production integrations are outside this local implementation's verified scope.
