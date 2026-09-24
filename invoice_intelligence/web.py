from pathlib import Path
from flask import Flask, jsonify, request, render_template
from .pipeline import extract_invoice, ingest_text, list_documents


def create_app(db_path=Path("var/invoices.sqlite"), contracts=None):
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 150000
    contracts = contracts or {}

    @app.get("/")
    def home():
        return render_template("index.html")

    @app.get("/health")
    def health():
        return {"status": "ok", "extractor": "deterministic-text-v1"}

    @app.get("/api/invoices")
    def invoices():
        return jsonify(list_documents(db_path))

    @app.post("/api/invoices")
    def submit():
        # JSON-only same-origin local UI avoids cross-site HTML form submissions.
        if not request.is_json:
            return {"error": "JSON request required"}, 415
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or not isinstance(payload.get("text"), str):
            return {"error": "Provide an object with an invoice text string"}, 422
        try:
            invoice = extract_invoice(payload["text"])
            result = ingest_text(payload["text"], db_path, contracts.get(invoice.contract_id))
            return result, 200 if result["duplicate"] else 201
        except ValueError as exc:
            return {"error": str(exc)}, 422

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'"
        return response
    return app
