"""Entry point. `python run.py --input input_examples/example_1.json` or `python run.py --serve`."""
from __future__ import annotations
import argparse, json, sys


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input")
    ap.add_argument("--serve", action="store_true")
    a = ap.parse_args()
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
