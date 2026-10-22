# app/: core agent logic (TODO, written in Cursor during the build window)
- `agents/`: Planner, Retriever, Evaluator/Critic, Synthesizer, Reviewer (TODO)
- `adapters/`: one adapter per external service, each with a timeout and a SAMPLE_MODE fallback
- Single shared model "generator" function configured via env (Meterless rule: engines never call the model directly)
