#!/bin/zsh
set -euo pipefail

cd /Users/minhwankim/workspace/260325_Clade_Meetagain
pkill -f 'src.app' || true
exec python3 -m src.app
