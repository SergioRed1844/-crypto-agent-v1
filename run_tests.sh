#!/usr/bin/env bash
# Corre todas las pruebas (sin red, sin dinero). Uso: ./run_tests.sh
set -e
cd "$(dirname "$0")"
for t in test_smoke test_recovery test_stress test_execution test_onchain test_context test_paper test_radar test_rebotes; do
  printf "%-16s " "$t"; python -m tests.$t 2>/dev/null | tail -1
done
