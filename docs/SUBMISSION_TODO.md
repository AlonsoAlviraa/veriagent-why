# Submission TODO (open items for Alonso)

Placeholders left empty on purpose; nothing here is invented.

| Item | Where | Status |
|---|---|---|
| `hackos_email` | `metadata.json` → `team[0].hackos_email` | TODO: Alonso fills in the HackOS account email |
| `demo_video_url` | `metadata.json`, README | TODO: upload the video (public/unlisted), paste link |
| `slide_deck_url` | `metadata.json`, README | TODO: publish the deck, paste link |
| Demo shot 5 live take | `docs/DEMO_SCRIPT.md` shot 5 | TODO: record example_2 live on Zetaris + Nightshift; no such live take exists yet |
| New Nightshift receipts with `agent` + `request_id` | `eval/nightshift_live/v2_agent_ids/` | TODO: the committed receipts (25 Oct) carry `client_request_id` but no `agent` field; re-run the 3 examples with Nightshift 1.2.7 up (`SAMPLE_MODE=false ZETARIS_BACKEND=sample LLM_PROVIDER=nightshift LLM_FALLBACK=none`) and commit `logs/receipts-*.jsonl` there |
| Live dev-split re-run | `eval/RESULTS_dev_*.md`, `output_examples/example_4_live_nvidia.json` | TODO: `python -m eval.eval --split dev` through Nightshift or NVIDIA (free tier). Current committed figures are from 22 Oct (direct NVIDIA, Super VL): agent 14/22, plain RAG 11/22 |
| PR #18 (`feat/test-battery`) | GitHub | TODO: merge of `main` into the branch is ready locally but the push was not approved; until merged, README links to `docs/TEST_BATTERY_REPORT.md` and `docs/V10_RESULTS.md` point to that branch |
