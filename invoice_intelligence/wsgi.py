import json
from pathlib import Path
from .web import create_app

app = create_app(Path("var/invoices.sqlite"), json.loads(Path("examples/contracts.json").read_text()))
