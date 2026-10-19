"""python -m radar scan | backtest | digest   (agrega --offline para usar solo la caché, --dry para no enviar)."""
import argparse
import json
import logging
import sys

from . import pipeline


def main(argv=None):
    ap = argparse.ArgumentParser(prog="radar")
    ap.add_argument("cmd", choices=["scan", "backtest", "digest"])
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    if a.cmd == "backtest":
        ev = pipeline.backtest(a.offline)
        print(json.dumps(ev["alerts_summary"], ensure_ascii=False))
    else:
        out = pipeline.run(a.offline, force_digest=(a.cmd == "digest"), dry=a.dry)
        print(json.dumps(out, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
