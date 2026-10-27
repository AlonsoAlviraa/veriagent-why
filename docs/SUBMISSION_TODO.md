# Submission TODO (open items for Alonso)

Placeholders left empty on purpose; nothing here is invented.

| Item | Where | Status |
|---|---|---|
| `hackos_email` | `metadata.json` → `team[0].hackos_email` | DONE: `alonso.alvbal@gmail.com` (HackOS account email) |
| `demo_video_url` | `metadata.json`, README | DONE: Google Drive link added (27 Oct 2026); folder shared "Anyone with the link, Viewer" |
| `slide_deck_url` | `metadata.json`, README | DONE: Drive PDF link added (PPTX in README); folder shared "Anyone with the link, Viewer" |
| Demo shot 5 live take | `docs/DEMO_SCRIPT.md` shot 5 | DONE (code & live execution verified 26 Oct 2026 on Zetaris JDBC + Nightshift 1.2.7: `output_examples/example_5_live_zetaris_nightshift.json` and `eval/nightshift_live/v2_agent_ids/zetaris-receipts-example-001..003.jsonl`, 72/72 receipts OK). Ready for screen recording via `.\scripts\windows\demo_video.ps1 -Step all` |
| New Nightshift receipts with `agent` + `request_id` | `eval/nightshift_live/v2_agent_ids/` | DONE (both Live Zetaris JDBC and sample backend): `zetaris-receipts-example-001..003.jsonl` (72/72 OK, 0 failed) and `sample-receipts-example-001..003.jsonl`, with `agent` on all agent calls and `client_request_id` (`X-Request-Id`) on all calls |
| Live dev-split re-run | `eval/RESULTS_dev_*.md`, `output_examples/example_4_live_nightshift.json` | DONE (26 Oct, Nightshift 1.2.7): `eval/RESULTS_dev_nightshift.md` (agent 21/22 vs plain RAG 12/22, in-sample post-guardrails, 405 ok / 3 failed calls = 99.3%) and `output_examples/example_4_live_nightshift.json`. Pre-guardrails 22 Oct NVIDIA run (14/22 vs 11/22) kept in `eval/RESULTS_dev_nvidia.md` |
| PR #18 (`feat/test-battery`) | GitHub | DONE: merged into `main` (`8901ba5`) |
