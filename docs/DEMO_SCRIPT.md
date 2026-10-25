# Demo video: shot list, voiceover and checklist (target 3:00; hard limits 1–4 min)

Track wording (identical in README, deck and video): **Track 02, "The Agent That Can Explain Why"**.
User story (one only): **an e-commerce ops analyst asks "why did on-time delivery drop?" over data federated in Zetaris.** V7/V9 is shown only as a secondary trust layer.

Recording launcher on the Windows PC: `.\scripts\windows\demo_video.ps1 -Step all` (or one step at a time: `pins`, `zetaris`, `run`, `mutate`, `receipts`). Waits may be cut; input and output must be real.

**Never on screen:** `.env`, the Nightshift `proxy-token` or its state folder, the Nightshift key/Setup screen with the key field, the Zetaris Docker login file (`/workspace/hackathons/zetaris_docker_login.txt` on the build box, or any copy), terminal history with secrets, the browser password manager. Close those windows before recording; review the final cut frame by frame.

## Shot list
| # | Time | Screen | Voiceover (English) |
|---|---|---|---|
| 1 | 0:00–0:15 | Title card: name, Track 02, "The Agent That Can Explain Why" | "VeriAgent Why, for Track 02: the agent that can explain why. Built for the ops analyst who sees a KPI drop and has to explain it before the Monday meeting." |
| 2 | 0:15–0:35 | Architecture diagram `docs/diagrams/veriagent_why_arch_v6.3.png` | "Six agents: a Planner proposes competing causes, a Retriever queries Zetaris, a relevance filter and an Evidence Evaluator test each cause against the data and can send the Planner back, a Cause Analyst ranks, a Writer drafts. A deterministic traceability check re-runs every cited query before anything reaches the memo." |
| 3 | 0:35–0:50 | Terminal: `demo_video.ps1 -Step pins` output (routed_model = pinned Lightning / Ultra) | "Every model call goes through Meterless Nightshift as the primary provider. At start-up we pin the exact Nemotron models and stop if routing differs." |
| 4 | 0:50–1:05 | Zetaris UI showing the views / `-Step zetaris` output | "The data lives in Zetaris: orders and logistics in Postgres, tickets from a REST source, federated into five views." |
| 5 | 1:05–1:50 | `-Step run` on example_2 (planted trap: the question blames the promotion) | "Here is the trap. The question says the promotion caused the drop. The agents test that claim, the evaluator finds the data refutes it, and the memo names a carrier SLA breach in one region instead, with the rows it cites." |
| 6 | 1:50–2:05 | Trace JSONL lines: planner → retriever → evaluator → `send_back_to_planner` | "This is the trace: each agent hand-off and the evaluator sending the planner back for more evidence." |
| 7 | 2:05–2:35 | `-Step mutate`: GREEN → change a cited row in the source → RED → restore → GREEN | "Receipts are reproducible. We change one cited row in the source database behind Zetaris; the claim turns red. Restore it; green again. Green means the cited data can be re-found, not that the claim is true." |
| 8 | 2:35–2:50 | `-Step receipts` table: agent → Nemotron model, ok | "Every call has a receipt: which agent, which Nemotron model, latency and tokens. The log is linked from the README." |
| 9 | 2:50–3:05 | Memo (PDF/UI) with confidence and Limitations section | "The memo gives a deterministic confidence score and its limits. Our honest numbers: live, the agent beat plain RAG 14 to 11 out of 22, but a trivial rule gets 13, so this is a start, not a proven win." |
| 10 | 3:05–3:15 | Closing card: repo URL, Meterless H-MEM + Markovian + Nightshift, Zetaris, NVIDIA Nemotron | "Code, traces and receipts are in the public repo. Thanks." |

## Checklist before upload
- [ ] Audio voiceover audible over the whole video; 1–4 min (aim 3:00).
- [ ] Track 02 named with the same wording as README and deck.
- [ ] ≥2 agents collaborating visible (trace hand-offs, send-back loop).
- [ ] Real execution (live run on Zetaris through Nightshift); cuts only of waiting.
- [ ] Zetaris doing real work (views queried, source mutation re-checked through JDBC).
- [ ] Meterless doing real work (Nightshift receipts; H-MEM ledger / Markovian rounds in the trace).
- [ ] Planted-trap demo (example_2) and mutation demo (green → red → green).
- [ ] No keys, tokens, `.env`, Zetaris login file or personal data in any frame (frame-by-frame review).
- [ ] Uploaded public/unlisted, opens in a private window without sign-in; stays up until judging ends.
- [ ] Backup copy kept (second host or Drive) and its link noted.
- [ ] Link added to README and `metadata.json` (`demo_video_url`).
