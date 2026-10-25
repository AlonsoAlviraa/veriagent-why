# Submission TODO (open items for Alonso)

Placeholders left empty on purpose; nothing here is invented.

| Item | Where | Status |
|---|---|---|
| `hackos_email` | `metadata.json` → `team[0].hackos_email` | TODO: Alonso fills in the HackOS account email |
| `demo_video_url` | `metadata.json`, README | TODO: upload the video (public/unlisted), paste link |
| `slide_deck_url` | `metadata.json`, README | TODO: publish the deck, paste link |
| Demo shot 5 live take | `docs/DEMO_SCRIPT.md` shot 5 | TODO (Alonso): record the take. Nightshift live receipts exist on the SAMPLE backend (`eval/nightshift_live/v2_agent_ids/`); the live-Zetaris + Nightshift attempt on 25 Oct failed (Nightshift 502 on every attempt), so shot 5 must not claim live Zetaris until a take actually succeeds |
| New Nightshift receipts with `agent` + `request_id` | `eval/nightshift_live/v2_agent_ids/` | DONE (sample backend): 3 examples, `agent` on all calls except pin checks, `client_request_id` on all; upstream `request_id` only on 502 responses. Live-Zetaris run: FAILED, not committed |
| Live dev-split re-run | `eval/RESULTS_dev_*.md`, `output_examples/example_4_live_nvidia.json` | TODO: `python -m eval.eval --split dev` through Nightshift or NVIDIA (free tier). Current committed figures are from 22 Oct (direct NVIDIA, Super VL): agent 14/22, plain RAG 11/22 |
| PR #18 (`feat/test-battery`) | GitHub | Merge of `main` pushed (041da03, no force), CI green, MERGEABLE. Alonso decides the merge |
