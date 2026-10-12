import logging

# httpx/httpcore registran la URL completa en INFO; FRED y CryptoPanic llevan la key en la URL.
for _n in ("httpx", "httpcore"):
    logging.getLogger(_n).setLevel(logging.WARNING)
