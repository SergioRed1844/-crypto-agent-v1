"""Agente FX (agente 3): intradía por datos macro sobre OANDA v20.

Modos (FX_MODE): ``backtest`` | ``paper`` (simulador local con precios en vivo) | ``practice`` (cuenta demo
fxPractice de OANDA) | ``live``. Claude nunca activa ``live``: requiere que un humano ponga a la vez
``FX_MODE=live`` y ``FX_LIVE_CONFIRM=SI-ENTIENDO-EL-RIESGO`` después de pasar la compuerta de práctica.
"""
