"""Precompute NVIDIA prompt-task-and-complexity-classifier features for benchmark items (CPU, offline after download).

Model: nvidia/prompt-task-and-complexity-classifier (Hugging Face, open weights, NVIDIA Open Model License,
DeBERTa-v3-base backbone). Model code below follows the model card's reference implementation.
Runs in a separate venv (torch CPU + transformers) so the main app/bench venv stays torch-free:

    /workspace/nvclf/venv/bin/python scripts/nv_classify.py --bench tatqa --limit 40
    /workspace/nvclf/venv/bin/python scripts/nv_classify.py --bench insightbench --limit 20

Output: bench/features/nvclf-<bench>.json  {item_id: {task_type_1, prompt_complexity_score, reasoning, ...}}
The Markovian controller only reads this JSON (deterministic, testable, no torch at run time).
"""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path
import numpy as np
import torch
import torch.nn as nn
from huggingface_hub import PyTorchModelHubMixin
from huggingface_hub import hf_hub_download
from transformers import AutoModel, DebertaV2TokenizerFast

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MID = "nvidia/prompt-task-and-complexity-classifier"


class MeanPooling(nn.Module):
    def forward(self, h, mask):
        m = mask.unsqueeze(-1).expand(h.size()).float()
        return torch.sum(h * m, 1) / torch.clamp(m.sum(1), min=1e-9)


class MulticlassHead(nn.Module):
    def __init__(self, n_in, n_out):
        super().__init__()
        self.fc = nn.Linear(n_in, n_out)

    def forward(self, x):
        return self.fc(x)


class CustomModel(nn.Module, PyTorchModelHubMixin):
    def __init__(self, target_sizes, task_type_map, weights_map, divisor_map):
        super().__init__()
        self.backbone = AutoModel.from_pretrained("microsoft/DeBERTa-v3-base")
        self.target_sizes = target_sizes.values()
        self.task_type_map, self.weights_map, self.divisor_map = task_type_map, weights_map, divisor_map
        self.heads = [MulticlassHead(self.backbone.config.hidden_size, sz) for sz in self.target_sizes]
        for i, h in enumerate(self.heads):
            self.add_module(f"head_{i}", h)
        self.pool = MeanPooling()

    def _score(self, logits, target):
        p = torch.softmax(logits, dim=1).detach().cpu().numpy()
        s = (p * np.array(self.weights_map[target])).sum(1) / self.divisor_map[target]
        s = [round(float(v), 4) for v in s]
        return [x if x >= 0.05 else 0 for x in s] if target == "number_of_few_shots" else s

    def forward(self, batch):
        h = self.backbone(input_ids=batch["input_ids"], attention_mask=batch["attention_mask"]).last_hidden_state
        x = self.pool(h, batch["attention_mask"])
        lg = [self.heads[k](x) for k in range(len(self.target_sizes))]
        pr = torch.softmax(lg[0], dim=1)
        top = torch.topk(pr, k=1, dim=1)
        r = {"task_type_1": [self.task_type_map[str(i)] for i in top.indices[:, 0].tolist()],
             "task_type_prob": [round(float(v), 3) for v in top.values[:, 0].tolist()]}
        for k, t in enumerate(["creativity_scope", "reasoning", "contextual_knowledge", "number_of_few_shots",
                               "domain_knowledge", "no_label_reason", "constraint_ct"], start=1):
            r[t] = self._score(lg[k], t)
        r["prompt_complexity_score"] = [round(0.35 * c + 0.25 * rs + 0.15 * ct + 0.15 * d + 0.05 * cx + 0.05 * f, 5)
                                        for c, rs, ct, d, cx, f in zip(r["creativity_scope"], r["reasoning"], r["constraint_ct"],
                                                                       r["domain_knowledge"], r["contextual_knowledge"], r["number_of_few_shots"])]
        return r


def prompts(bench: str, limit: int):
    from bench.run import select
    tasks = select(bench, False, limit, None)
    if bench == "tatqa":
        return [(t["id"], "Prompt: " + t["q"]["question"]) for t in tasks]
    return [(t["id"], "Prompt: " + t["metadata"]["goal"]) for t in tasks]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", choices=["tatqa", "insightbench"], required=True)
    ap.add_argument("--limit", type=int, default=40)
    a = ap.parse_args()
    torch.manual_seed(0)
    cfg = json.loads(Path(hf_hub_download(MID, "config.json")).read_text())  # no model_type key -> read raw
    tok = DebertaV2TokenizerFast.from_pretrained(MID)
    model = CustomModel.from_pretrained(MID).eval()  # init kwargs come from config.json (mixin)
    out, t0 = {}, time.time()
    for iid, p in prompts(a.bench, a.limit):
        enc = tok([p], return_tensors="pt", add_special_tokens=True, max_length=512, padding="max_length", truncation=True)
        with torch.no_grad():
            r = model(enc)
        out[iid] = {k: v[0] for k, v in r.items()}
    dst = ROOT / "bench" / "features" / f"nvclf-{a.bench}.json"
    dst.write_text(json.dumps({"model": MID, "runtime": "CPU, local open weights", "items": out}, indent=1))
    print(f"{len(out)} items in {time.time() - t0:.1f}s -> {dst}")


if __name__ == "__main__":
    main()
