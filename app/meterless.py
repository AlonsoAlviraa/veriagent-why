"""Client for the Meterless bridge (vendored open-source H-MEM + Markovian engines, run with node)."""
from __future__ import annotations
import json, shutil, subprocess
from .config import ROOT

BRIDGE = ROOT / "meterless_bridge" / "dist" / "bridge.mjs"


class Bridge:
    def __init__(self):
        node = shutil.which("node")
        if not node or not BRIDGE.exists():
            raise RuntimeError("node or meterless_bridge/dist/bridge.mjs not available")
        self.p = subprocess.Popen([node, str(BRIDGE)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
        self.n = 0

    def _send(self, obj: dict) -> None:
        self.p.stdin.write(json.dumps(obj, default=str) + "\n"); self.p.stdin.flush()

    def call(self, op: str, on_step=None, **args):
        self.n += 1
        mid = self.n
        self._send({"id": mid, "op": op, "args": args})
        while True:
            line = self.p.stdout.readline()
            if not line:
                raise RuntimeError("meterless bridge exited")
            msg = json.loads(line)
            if msg.get("event") == "step":
                self._send({"op": "step.result", "content": on_step(msg)})
                continue
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(msg["error"])
                return msg["result"]

    def close(self) -> None:
        try:
            self.p.stdin.close(); self.p.wait(timeout=5)
        except Exception:
            self.p.kill()
