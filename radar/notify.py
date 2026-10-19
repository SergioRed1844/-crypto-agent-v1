"""Canales de entrega. Cada uno se activa solo si existen sus secrets; ninguno imprime llaves ni URLs con llaves.

- issue   : GitHub Issues del repo (GITHUB_TOKEN de Actions). GitHub te manda cada issue/comentario por correo. Gratis.
- email   : Gmail SMTP con contraseña de aplicación (RADAR_SMTP_USER, RADAR_SMTP_PASS, RADAR_EMAIL_TO opcional). Privado.
- whatsapp: CallMeBot (CALLMEBOT_PHONE, CALLMEBOT_APIKEY). Gratis, solo a tu propio número.
"""
from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from . import config as C
from .report import md_to_html

log = logging.getLogger("radar.notify")
LOG: list[str] = []      # bitácora sin secretos (va al estado)


def _ok(msg):
    LOG.append(msg)
    log.info(msg)


def channels() -> list[str]:
    want = [x.strip() for x in os.getenv("RADAR_CHANNELS", "issue,email,whatsapp").split(",") if x.strip()]
    have = []
    if "issue" in want and os.getenv("GITHUB_TOKEN") and os.getenv("GITHUB_REPOSITORY"):
        have.append("issue")
    if "email" in want and os.getenv("RADAR_SMTP_USER") and os.getenv("RADAR_SMTP_PASS"):
        have.append("email")
    if "whatsapp" in want and os.getenv("CALLMEBOT_PHONE") and os.getenv("CALLMEBOT_APIKEY"):
        have.append("whatsapp")
    return have


def _gh(method: str, path: str, json_body: dict | None = None):
    import httpx
    tok = os.environ["GITHUB_TOKEN"]
    url = f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}{path}"
    r = httpx.request(method, url, json=json_body, timeout=30,
                      headers={"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json",
                               "X-GitHub-Api-Version": "2022-11-28"})
    if r.status_code >= 300:
        raise RuntimeError(f"GitHub {method} {path}: HTTP {r.status_code} {r.text[:160]}")
    return r.json()


def issue_create(title: str, body: str, labels: list[str]) -> int | None:
    try:
        try:
            js = _gh("POST", "/issues", {"title": title[:240], "body": body[:65000], "labels": labels})
        except RuntimeError:
            js = _gh("POST", "/issues", {"title": title[:240], "body": body[:65000]})
        _ok(f"issue #{js['number']} creado")
        return int(js["number"])
    except Exception as e:  # noqa: BLE001
        _ok(f"issue falló: {type(e).__name__}: {str(e)[:160]}")
        return None


def issue_comment(number: int, body: str) -> bool:
    try:
        _gh("POST", f"/issues/{number}/comments", {"body": body[:65000]})
        _ok(f"comentario en #{number}")
        return True
    except Exception as e:  # noqa: BLE001
        _ok(f"comentario falló: {type(e).__name__}: {str(e)[:160]}")
        return False


def email_send(subject: str, md: str) -> bool:
    user, pwd = os.getenv("RADAR_SMTP_USER", ""), os.getenv("RADAR_SMTP_PASS", "")
    to = os.getenv("RADAR_EMAIL_TO") or user
    host = os.getenv("RADAR_SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("RADAR_SMTP_PORT", "465"))
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    msg.attach(MIMEText(md, "plain", "utf-8"))
    msg.attach(MIMEText(md_to_html(md), "html", "utf-8"))
    try:
        with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=30) as s:
            s.login(user, pwd)
            s.sendmail(user, [to], msg.as_string())
        _ok("correo enviado")
        return True
    except Exception as e:  # noqa: BLE001 — sin credenciales en el mensaje
        _ok(f"correo falló: {type(e).__name__}")
        return False


def whatsapp_send(text: str) -> bool:
    import httpx
    try:
        r = httpx.get("https://api.callmebot.com/whatsapp.php", timeout=30,
                      params={"phone": os.environ["CALLMEBOT_PHONE"], "text": text[:900],
                              "apikey": os.environ["CALLMEBOT_APIKEY"]})
        ok = r.status_code == 200 and "error" not in r.text.lower()[:200]
        _ok("whatsapp enviado" if ok else f"whatsapp respondió HTTP {r.status_code}")
        return ok
    except Exception as e:  # noqa: BLE001 — la URL lleva la apikey: nunca se registra
        _ok(f"whatsapp falló: {type(e).__name__}")
        return False


def send_alert(title: str, md: str, short: str) -> dict:
    sent = {}
    ch = channels()
    if "issue" in ch:
        sent["issue"] = issue_create(title, md, ["radar-alerta"])
    if "email" in ch:
        sent["email"] = email_send(title, md)
    if "whatsapp" in ch:
        sent["whatsapp"] = whatsapp_send(short)
    if not ch:
        _ok("sin canales configurados: la alerta queda solo en data/radar/")
    return sent


def send_digest(title: str, md: str, state: dict, month: str) -> dict:
    sent = {}
    ch = channels()
    if "issue" in ch:
        num = (state.setdefault("digest_issue", {})).get(month)
        if num is None:
            num = issue_create(f"📡 Radar EB — resúmenes {month}", "Un comentario por día con el resumen del Radar.",
                               ["radar-resumen"])
            if num:
                state["digest_issue"][month] = num
        sent["issue"] = issue_comment(num, md) if num else False
    if "email" in ch:
        sent["email"] = email_send(title, md)
    if "whatsapp" in ch and os.getenv("RADAR_WHATSAPP_DIGEST") == "1":
        sent["whatsapp"] = whatsapp_send(title + " — sigo vivo. Detalle en tu correo.")
    return sent
