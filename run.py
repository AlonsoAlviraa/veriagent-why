"""Entry point. `python run.py --input input_examples/example_1.json` (or positional) or `python run.py --serve`."""
from __future__ import annotations
import argparse, json, os


def main() -> None:
    from app.config import load_dotenv
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("input_pos", nargs="?", metavar="INPUT", help="input JSON (same as --input)")
    ap.add_argument("--input")
    ap.add_argument("--brief", action="store_true", help="omit the full result object")
    ap.add_argument("--serve", action="store_true")
    ap.add_argument("--ui", action="store_true", help="serve the web UI (separate port, UI_PORT default 8501)")
    a = ap.parse_args()
    if a.ui:
        import uvicorn
        uvicorn.run("app.ui:ui", host="0.0.0.0", port=int(os.environ.get("UI_PORT") or 8501))
        return
    if a.serve:
        import uvicorn
        uvicorn.run("app.api:app", host="0.0.0.0", port=int(os.environ.get("PORT") or 8000))
        return
    path = a.input or a.input_pos
    if not path:
        ap.error("give an input file: python run.py --input input_examples/example_1.json")
    from app.pipeline import run
    req = json.load(open(path))
    if isinstance(req.get("options"), dict) and "sample_mode" in req["options"] and not os.environ.get("SAMPLE_MODE"):
        os.environ["SAMPLE_MODE"] = "true" if req["options"]["sample_mode"] else "false"
    res = run(req["input"], req.get("run_id"))
    if a.brief:
        res["output"].pop("result", None)
    print(json.dumps(res, indent=2, default=str))


if __name__ == "__main__":
    main()
