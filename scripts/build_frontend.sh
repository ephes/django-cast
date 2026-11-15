#!/usr/bin/env bash
# Build and copy the shipped Vite assets, independent of the caller's directory.
set -euo pipefail
cd "$(dirname "$0")/.."
cd javascript
npm run build
# Vite places its manifest in .vite; django-vite expects it beside the assets.
mv dist/.vite/manifest.json dist/manifest.json
python3 -c 'from pathlib import Path; p=Path("dist/manifest.json"); p.write_text(p.read_text().rstrip("\n") + "\n")'
rmdir dist/.vite
rm -f ../src/cast/static/cast/vite/*
cp dist/* ../src/cast/static/cast/vite/
