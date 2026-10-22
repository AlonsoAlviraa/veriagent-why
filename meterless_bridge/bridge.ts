// JSON-lines bridge between the Python agents and the Meterless engines (H-MEM + Markovian).
// stdin:  {"id":n,"op":"...","args":{...}} or {"op":"step.result","content":"..."}
// stdout: {"id":n,"result":...} | {"id":n,"error":"..."} | {"event":"step",...}
// Deterministic: injected counter clock. No network.
import { HMEM } from "../vendor/meterless/hmem/index.ts";
import { Markovian, resetRunSeq } from "../vendor/meterless/markovian/index.ts";
import { setEmbedOverride } from "../vendor/meterless/hmem/embeddings.ts";
import * as readline from "node:readline";

// Real embeddings supplied by the Python host (NVIDIA) keyed by exact text; absent -> vendored hash embedder.
const vecs = new Map<string, number[]>();
setEmbedOverride((text) => vecs.get(text));

let t = 1_790_000_000_000;
const clock = () => (t += 1000);
let hmem = new HMEM({ clock, actor: "veriagent-why" });
let stepWaiter: ((c: string) => void) | null = null;
const out = (o: unknown) => process.stdout.write(JSON.stringify(o) + "\n");

async function handle(msg: any): Promise<unknown> {
  const a = msg.args ?? {};
  switch (msg.op) {
    case "reset":
      t = 1_790_000_000_000; resetRunSeq(); vecs.clear(); hmem = new HMEM({ clock, actor: "veriagent-why" }); return { ok: true };
    case "hmem.add": {
      if (Array.isArray(a.embedding)) vecs.set(a.content, a.embedding);
      const r = hmem.add({ content: a.content, type: "factual", layer: a.layer ?? "working", tags: a.tags ?? [],
        confidence: a.confidence ?? 0.8, source: a.source, derivedFrom: a.derivedFrom, missionId: a.missionId });
      return { id: r.id };
    }
    case "hmem.query": {
      if (Array.isArray(a.queryEmbedding)) vecs.set(a.query, a.queryEmbedding);
      const q = hmem.query(a.query, { topN: a.topN ?? 5, threshold: a.threshold ?? 0.1 });
      return { context: q.context, ids: (q as any).memories?.map((m: any) => m.id ?? m.memory?.id) ?? [] };
    }
    case "hmem.ledger":
      return { entries: hmem.ledger.all(), stats: hmem.ledger.stats() };
    case "markovian.run": {
      const m = new Markovian({ clock, chunkConfig: { chunkSize: a.chunkSize ?? 4000, carryoverTokens: a.carryoverTokens ?? 640, maxChunks: a.maxChunks ?? 3 } });
      const run = await m.run({
        goal: a.goal, memoryContext: a.memoryContext, mode: "RESEARCH", reflect: false,
        stepFn: ({ step, carryover, prompt }) => new Promise((resolve) => {
          stepWaiter = (content) => resolve({ content });
          out({ event: "step", id: msg.id, step, carryover, prompt_chars: prompt.length });
        }),
      });
      return { id: run.id, status: run.status, chunks: run.chunks.map((c) => ({ id: c.id, tokens: c.tokens, carryover_chars: c.carryover.length })),
               totalTokensUsed: run.totalTokensUsed, totalTokensSaved: run.totalTokensSaved,
               efficiencyPercent: run.efficiencyPercent, tokenLabel: run.tokenLabel, chunkConfig: run.chunkConfig };
    }
    default:
      throw new Error(`unknown op ${msg.op}`);
  }
}

const rl = readline.createInterface({ input: process.stdin });
rl.on("line", (line) => {
  if (!line.trim()) return;
  const msg = JSON.parse(line);
  if (msg.op === "step.result") { const w = stepWaiter; stepWaiter = null; w?.(msg.content); return; }
  handle(msg).then((result) => out({ id: msg.id, result }), (e) => out({ id: msg.id, error: String(e?.message ?? e) }));
});
