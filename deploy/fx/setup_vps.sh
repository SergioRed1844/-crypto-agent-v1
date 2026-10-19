#!/usr/bin/env bash
# Instala fx-agente en un VPS Ubuntu 22.04/24.04 limpio. Uso (como root):
#   curl -fsSL https://raw.githubusercontent.com/SergioRed1844/-crypto-agent-v1/fx-agente/deploy/fx/setup_vps.sh | bash
# Después: edita /etc/fx-agente.env (token DEMO de OANDA, cuenta, secreto), tu dominio en /etc/caddy/Caddyfile y
#   systemctl enable --now fx-agente fx-monitor caddy
set -euo pipefail
apt-get update -q
apt-get install -y -q git python3-venv python3-pip chrony ufw debian-keyring debian-archive-keyring apt-transport-https curl
# Reloj: la latencia se mide contra la hora de OANDA; sin NTP los timestamps no sirven
systemctl enable --now chrony
# Caddy (TLS automático)
if ! command -v caddy >/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -q && apt-get install -y -q caddy
fi
id fxagent >/dev/null 2>&1 || useradd --system --create-home --shell /usr/sbin/nologin fxagent
mkdir -p /var/lib/fx-agente && chown fxagent:fxagent /var/lib/fx-agente
if [ ! -d /opt/fx-agente/.git ]; then
  git clone --depth 1 --branch fx-agente https://github.com/SergioRed1844/-crypto-agent-v1.git /opt/fx-agente
fi
python3 -m venv /opt/fx-agente/.venv
/opt/fx-agente/.venv/bin/pip install -q -r /opt/fx-agente/fx/requirements.txt
chown -R fxagent:fxagent /opt/fx-agente
[ -f /etc/fx-agente.env ] || { cp /opt/fx-agente/deploy/fx/fx-agente.env.example /etc/fx-agente.env; chmod 600 /etc/fx-agente.env; }
cp /opt/fx-agente/deploy/fx/fx-agente.service /opt/fx-agente/deploy/fx/fx-monitor.service /etc/systemd/system/
grep -q "127.0.0.1:8080" /etc/caddy/Caddyfile 2>/dev/null || cp /opt/fx-agente/deploy/fx/Caddyfile /etc/caddy/Caddyfile
systemctl daemon-reload
ufw allow 22/tcp && ufw allow 80/tcp && ufw allow 443/tcp && ufw --force enable
echo "Listo. Falta: editar /etc/fx-agente.env y /etc/caddy/Caddyfile; luego:"
echo "  bash -c 'set -a; . /etc/fx-agente.env; cd /opt/fx-agente; .venv/bin/python -m fx check'"
echo "  systemctl enable --now fx-agente fx-monitor caddy"
