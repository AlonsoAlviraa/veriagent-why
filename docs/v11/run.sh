cd /tmp/cc && source <env.sh: config_v11.json env + provider key, not committed> && export NEBIUS_STRICT=1 NEBIUS_BUDGET_USD=18.65 TATQA_SPLIT=v11_tablebench
k=$1
/tmp/rv/bin/python -m bench.run --bench tatqa --systems agent_v9,rag --split-file /workspace/v11/shards/s$k.json --max-calls 3000 --max-calls-item 40 --no-judge --trace-dir /workspace/v11/runs/tr_$k --out /workspace/v11/runs/v11_$k.jsonl
echo SHARDDONE $k
