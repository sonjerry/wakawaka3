#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; DIR="$ROOT/.tools/mediamtx"; mkdir -p "$DIR"
case "$(uname -m)" in aarch64) A="arm64v8";; armv7l|armv6l) A="armv7";; *) echo "Unsupported arch"; exit 1;; esac
URL="$(python3 - "$A" <<'PY'
import json,sys,urllib.request
a=sys.argv[1];u="https://api.github.com/repos/bluenviron/mediamtx/releases/latest"
r=urllib.request.Request(u,headers={"User-Agent":"rc-simracing"})
d=json.load(urllib.request.urlopen(r,timeout=10))
for x in d["assets"]:
    if x["name"].endswith(f"linux_{a}.tar.gz"):
        print(x["browser_download_url"]);break
else: raise SystemExit("asset not found")
PY
)"
curl -L "$URL" -o "$DIR/mediamtx.tar.gz"
tar -xzf "$DIR/mediamtx.tar.gz" -C "$DIR"; chmod +x "$DIR/mediamtx"
echo "MediaMTX installed."
