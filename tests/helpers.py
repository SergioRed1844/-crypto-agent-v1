import time

H4 = 4 * 3_600_000


def last_bar_open(offset_bars: int = 0) -> int:
    """Apertura de la vela 4H que acaba de cerrar (alineada a 4H como la manda TradingView)."""
    now = int(time.time() * 1000)
    return (now // H4) * H4 - H4 - offset_bars * H4


def wait_for(fn, timeout=15, every=0.25):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = fn()
        if v:
            return v
        time.sleep(every)
    return fn()
