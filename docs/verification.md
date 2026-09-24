# Verification

Executed on September 24, 2026 with Python 3.12:

- 17 base behavioral tests: exact arithmetic and parsing, malformed inputs, PDF ingestion, contract mismatches, policy revalidation, batch isolation, idempotency including whitespace changes, numeric overflow, scheduler error-data minimization and web API behavior.
- Optional TensorFlow 2.21 smoke test: train on invented labeled lines with a document-disjoint split, save Keras model, reload it and run inference. Passed; Keras emitted upstream NumPy deprecation warnings.
- CLI ingested the valid and exception examples with expected statuses.
- Browser checked rendered review results and form submission. A whitespace duplicate bug discovered during that check was reproduced and fixed with a regression test.
- Python modules and DAG pass compile checks. Airflow scheduling and Docker container execution were not run. The DAG's underlying batch processing is covered by tests.

No production scale or extraction accuracy benchmark is claimed.
