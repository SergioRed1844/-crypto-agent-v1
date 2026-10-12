"""Motor de contexto v4.2: calendario de eventos (3 años), historia desde 2009, pesos por estudio de eventos,
vigía on-chain y la señal de contexto que consume el grafo de trading. Ver docs/MODELO_CONTEXTO.md."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def ctx_dir() -> Path:
    return Path(os.environ.get("CONTEXT_DIR", ROOT / "data" / "context"))


def read_json(name: str, default=None):
    p = ctx_dir() / name
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(name: str, obj) -> Path:
    p = ctx_dir() / name
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    tmp.replace(p)
    return p


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
