import argparse
import json
from pathlib import Path
from .pipeline import extract_invoice, ingest, list_documents, read_document


def main():
    parser = argparse.ArgumentParser(description="Extract invoices, validate contract terms, and store an audit record")
    parser.add_argument("command", choices=["ingest", "list", "serve"])
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--contracts", type=Path, default=Path("examples/contracts.json"))
    parser.add_argument("--db", type=Path, default=Path("var/invoices.sqlite"))
    parser.add_argument("--port", type=int, default=8050)
    args = parser.parse_args()
    contracts = json.loads(args.contracts.read_text())
    if args.command == "serve":
        from .web import create_app
        create_app(args.db, contracts).run(host="127.0.0.1", port=args.port)
    elif args.command == "list":
        print(json.dumps(list_documents(args.db), indent=2))
    else:
        if not args.paths:
            parser.error("ingest requires one or more .txt/.pdf paths")
        failed = False
        for path in args.paths:
            try:
                contract_id = extract_invoice(read_document(Path(path))).contract_id
                print(json.dumps(ingest(Path(path), args.db, contracts.get(contract_id)), indent=2))
            except (ValueError, OSError) as exc:
                failed = True
                print(json.dumps({"source": str(path), "status": "failed", "error": str(exc)}))
        if failed:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
