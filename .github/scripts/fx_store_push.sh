#!/usr/bin/env bash
# Copia el contenido de $1 a la rama `fx-data` (la crea huérfana si no existe) y empuja con las credenciales que
# deja actions/checkout. Uso: fx_store_push.sh DIR MSG   (se corre desde la raíz del checkout)
set -euo pipefail
mkdir -p "$1"
tmp="$(mktemp -d)"; cp -r "$1"/. "$tmp"/
git config user.name "fx-agente-bot"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
if git fetch -q --depth 1 origin fx-data 2>/dev/null; then
  git checkout -q -f -B fx-data FETCH_HEAD
else
  git checkout -q -f --orphan fx-data
  git rm -rfq . >/dev/null 2>&1 || true
  printf '# fx-data\n\nVelas de 1 minuto bid/ask (Dukascopy) para el agente FX. Las escribe `fx-data.yml`.\n' > README.md
fi
git clean -fdxq -e README.md
cp -r "$tmp"/. .
git add -A
git diff --cached --quiet && { echo "sin cambios"; exit 0; }
git commit -q -m "$2 [skip render]"
for i in 1 2 3 4; do
  git push -q origin HEAD:fx-data && { echo "publicado en fx-data"; exit 0; }
  git pull -q --rebase -X theirs origin fx-data || true; sleep $((i * 10))
done
echo "no se pudo empujar"; exit 1
