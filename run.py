"""Entry point. `python run.py --input input_examples/example_1.json` or `python run.py --serve`."""
from __future__ import annotations
import argparse, json, sys


def main() -> None:
    from app.config import load_dotenv
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--input")
    ap.add_argument("--serve", action="store_true")
    ap.add_argument("--ui", action="store_true", help="serve the web UI (separate port, UI_PORT default 8501)")
    a = ap.parse_args()
    if a.ui:
        import os, uvicorn
        uvicorn.run("app.ui:ui", host="0.0.0.0", port=int(os.environ.get("UI_PORT") or 8501))
        return
    if a.serve:
        import os, uvicorn
        uvicorn.run("app.api:app", host="0.0.0.0", port=int(os.environ.get("PORT") or 8000))
        return
    from app.pipeline import run
    req = json.load(open(a.input))
    res = run(req["input"], req.get("run_id"))
    res["output"].pop("result", None) if "--brief" in sys.argv else None
    print(json.dumps(res, indent=2, default=str))


if __name__ == "__main__":
    main()
