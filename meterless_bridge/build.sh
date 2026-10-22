#!/usr/bin/env sh
set -e
cd "$(dirname "$0")"
npx --yes esbuild@0.24.0 bridge.ts --bundle --platform=node --format=esm --target=node18 --outfile=dist/bridge.mjs
