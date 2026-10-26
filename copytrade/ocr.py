"""OCR propio de los 278-T: página a 300 dpi en grises → se borran las líneas de la tabla → tesseract --psm 6.
Con las líneas de la tabla tesseract no lee nada; sin ellas lee casi todo.

    python -m copytrade.ocr PDF OUT_TXT [JOBS]
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image


def delines(src: Path, dst: Path, thr: int = 140, frac: float = 0.35) -> None:
    im = np.array(Image.open(src).convert("L"))
    dark = im < thr
    out = im.copy()
    for y in np.where(dark.mean(axis=1) > frac)[0]:
        out[max(0, y - 1):y + 2, :] = 255
    for x in np.where(dark.mean(axis=0) > frac)[0]:
        out[:, max(0, x - 1):x + 2] = 255
    Image.fromarray(out).save(dst)


def _page(args) -> str:
    pdf, n, tmp = args
    base = Path(tmp) / f"p{n:04d}"
    subprocess.run(["pdftoppm", "-r", "300", "-gray", "-f", str(n), "-l", str(n), "-png", "-singlefile",
                    str(pdf), str(base)], check=True)
    delines(base.with_suffix(".png"), base.with_name(base.name + "q.png"))
    env = {**os.environ, "OMP_THREAD_LIMIT": "1"}
    r = subprocess.run(["tesseract", str(base.with_name(base.name + "q.png")), "-", "--psm", "6"],
                       capture_output=True, text=True, env=env)
    for p in (base.with_suffix(".png"), base.with_name(base.name + "q.png")):
        p.unlink(missing_ok=True)
    return f"\f=== page {n} ===\n" + r.stdout


def pages(pdf: Path) -> int:
    info = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True).stdout
    return int(next(l.split()[-1] for l in info.splitlines() if l.startswith("Pages:")))


def main(pdf: str, out: str, jobs: int = 2) -> int:
    p = Path(pdf)
    with tempfile.TemporaryDirectory() as tmp, ThreadPoolExecutor(jobs) as ex:
        txt = "".join(ex.map(_page, [(p, n, tmp) for n in range(1, pages(p) + 1)]))
    Path(out).write_text(txt)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 2))
