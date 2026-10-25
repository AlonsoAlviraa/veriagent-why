# Submission TODO (open items for Alonso)

Placeholders left empty on purpose; nothing here is invented.

| Item | Where | Status |
|---|---|---|
| `hackos_email` | `metadata.json` → `team[0].hackos_email` | TODO: Alonso fills in the HackOS account email |
| `demo_video_url` | `metadata.json`, README | TODO: upload the video (public/unlisted), paste link |
| `slide_deck_url` | `metadata.json`, README | TODO: publish the deck, paste link |
| Demo shot 5 live take | `docs/DEMO_SCRIPT.md` shot 5 | TODO (Alonso): record the take. Nightshift live receipts exist on the SAMPLE backend (`eval/nightshift_live/v2_agent_ids/`); the live-Zetaris + Nightshift attempt on 25 Oct failed (Nightshift 502 on every attempt), so shot 5 must not claim live Zetaris until a take actually succeeds |
| New Nightshift receipts with `agent` + `request_id` | `eval/nightshift_live/v2_agent_ids/` | DONE (sample backend): 3 examples, `agent` on all calls except pin checks, `client_request_id` on all; upstream `request_id` only on 502 responses. Live-Zetaris run: FAILED, not committed |
| Live dev-split re-run | `eval/RESULTS_dev_*.md`, `output_examples/example_4_live_nightshift.json` | DONE (25 Oct, Nightshift 1.2.7): `eval/RESULTS_dev_nightshift.md` (agent 21/22 vs plain RAG 12/22, in-sample post-guardrails, 111 ok / 225 HTTP-502 fallback calls) and `output_examples/example_4_live_nightshift.json`. Pre-guardrails 22 Oct NVIDIA run (14/22 vs 11/22) kept in `eval/RESULTS_dev_nvidia.md` |
| PR #18 (`feat/test-battery`) | GitHub | DONE: merged into `main` (`8901ba5`) |
