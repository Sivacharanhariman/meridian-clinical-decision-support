"""Run from repository root. --check detects drift without updating artifacts."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app import app

target = Path(__file__).resolve().parents[1] / "contracts/openapi.json"
value = json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"
if "--check" in sys.argv:
    if not target.exists() or target.read_text() != value:
        raise SystemExit("OpenAPI drift: run python scripts/export_openapi.py and npm run generate in frontend")
    print("OpenAPI is current")
else:
    target.write_text(value)
    print(target)
