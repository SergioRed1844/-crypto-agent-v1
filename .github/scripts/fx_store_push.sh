#!/usr/bin/env bash
# Copia el contenido de $1 a la rama `fx-data` (la crea huérfana si no existe) y empuja. Uso: fx_store_push.sh DIR MSG
set -euo pipefail
src="$(cd "$1" && pwd)"; msg="$2"
repo="https://x-access-token:${TOKEN}@github.com/${GITHUB_REPOSITORY}.git"
work="$(mktemp -d)"
if git clone -q --depth 1 --branch fx-data "$repo" "$work" 2>/dev/null; then :; else
  git -C "$work" init -q -b fx-data && git -C "$work" remote add origin "$repo"
  printf '# fx-data\n\nVelas de 1 minuto bid/ask (Dukascopy) para el agente FX. Las escribe `fx-data.yml`.\n' > "$work/README.md"
fi
cp -r "$src"/. "$work"/
cd "$work"
git config user.name "fx-agente-bot"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git add -A
git diff --cached --quiet && { echo "sin cambios"; exit 0; }
git commit -q -m "$msg [skip render]"
for i in 1 2 3 4; do
  git push -q origin HEAD:fx-data && exit 0
  git pull -q --rebase -X theirs origin fx-data || true; sleep $((i * 10))
done
echo "no se pudo empujar"; exit 1
