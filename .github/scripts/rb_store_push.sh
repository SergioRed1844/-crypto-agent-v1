#!/usr/bin/env bash
# Copia el contenido de $1 a la rama `copytrade-data` (la crea huérfana si no existe) y empuja con las credenciales
# que deja actions/checkout. Los archivos ya publicados se conservan salvo que se sobrescriban.
# Uso: ct_store_push.sh DIR MSG   (desde la raíz del checkout)
set -euo pipefail
BR=rebotes-data
mkdir -p "$1"
tmp="$(mktemp -d)"; cp -r "$1"/. "$tmp"/
git config user.name "rebotes-bot"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
if git fetch -q --depth 1 origin "$BR" 2>/dev/null; then
  git checkout -q -f -B "$BR" FETCH_HEAD
else
  git checkout -q -f --orphan "$BR"
  git rm -rfq . >/dev/null 2>&1 || true
  printf '# rebotes-data\n\nResultados del estudio de rebotes (docs/REBOTES.md de la rama rebotes). Lo escribe rebotes.yml.\n' > README.md
fi
git clean -fdxq -e README.md
cp -r "$tmp"/. .
git add -A
git diff --cached --quiet && { echo "sin cambios"; exit 0; }
git commit -q -m "$2 [skip render]"
for i in 1 2 3 4; do
  git push -q origin HEAD:"$BR" && { echo "publicado en $BR"; exit 0; }
  git pull -q --rebase -X theirs origin "$BR" || true; sleep $((i * 10))
done
echo "no se pudo empujar"; exit 1
