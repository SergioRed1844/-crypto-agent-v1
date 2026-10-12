"""Estado compartido del grafo. Cada analista escribe en su propia llave (fan-in sin choques)."""
import operator
from typing import Annotated, Any, Optional, TypedDict


class AnalystReport(TypedDict):
    agent: str
    vote: str          # LONG | FLAT | EXIT
    score: float       # -1.0 (muy bajista) .. +1.0 (muy alcista)
    confidence: int    # 0-100
    veto: bool         # True = bloqueo duro (p.ej. régimen RED, evento macro)
    reasons: list[str]


class AgentState(TypedDict, total=False):
    # Entrada
    signal: dict[str, Any]
    pair: str
    # Contexto de mercado (lo llena el nodo gather, sin LLM)
    market: dict[str, Any]
    portfolio: dict[str, Any]
    # Reportes de analistas (reducer: se concatenan los que corren en paralelo)
    reports: Annotated[list[AnalystReport], operator.add]
    # Debate y decisión
    bull_case: str
    bear_case: str
    judge: dict[str, Any]
    # Riesgo y ejecución (deterministas)
    risk: dict[str, Any]
    execution: dict[str, Any]
    # Trazabilidad
    decision_id: str
    errors: Annotated[list[str], operator.add]
    final_action: Optional[str]
