# Meterless bridge

`bridge.ts` exposes the vendored Meterless H-MEM and Markovian reference engines to the Python agents over JSON lines on stdin/stdout (no port, no network).
`dist/bridge.mjs` is the prebuilt bundle (committed so SAMPLE_MODE needs only `node`, no `npm install`). Rebuild with `./build.sh`.
