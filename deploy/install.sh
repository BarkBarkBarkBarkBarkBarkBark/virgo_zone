#!/usr/bin/env bash
set -euo pipefail

project_dir="${VIRGOZONE_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
service_user="${VIRGOZONE_USER:-${SUDO_USER:-jetson}}"
service_group="$(id -gn "$service_user" 2>/dev/null || echo "$service_user")"
service_source="$project_dir/deploy/virgozone.service"
avahi_source="$project_dir/deploy/virgozone-http.service"
environment_dir="/etc/virgozone"
environment_file="$environment_dir/env"
avahi_config="/etc/avahi/avahi-daemon.conf"

if [[ "$EUID" -ne 0 ]]; then
  echo "Run this appliance service installer with sudo, or run bash install.sh for user-level gateway install." >&2
  exit 1
fi

if [[ ! -f "$project_dir/requirements.txt" ]]; then
  echo "VirgoZone project was not found at $project_dir." >&2
  exit 1
fi

apt-get update
apt-get install -y avahi-daemon ffmpeg python3-venv

if [[ ! -x "$project_dir/.venv/bin/python" ]]; then
  runuser -u "$service_user" -- python3 -m venv "$project_dir/.venv"
fi
runuser -u "$service_user" -- "$project_dir/.venv/bin/python" -m pip install -r "$project_dir/requirements.txt" -e "$project_dir"

install -d -o "$service_user" -g "$service_group" -m 0750 "$project_dir/data"
install -d -o "$service_user" -g "$service_group" -m 0750 "$project_dir/data/uploads"
install -d -o "$service_user" -g "$service_group" -m 0750 "$project_dir/data/thumbnails"
install -d -o root -g root -m 0750 "$environment_dir"

if [[ ! -f "$environment_file" ]]; then
  install -m 0600 /dev/null "$environment_file"
  {
    printf 'APP_NAME=VirgoZone\n'
    printf 'DATA_DIR=%s/data\n' "$project_dir"
    printf 'ADMIN_PASSWORD=neuro\n'
    printf 'IMAGE_MAX_MB=20\n'
    printf 'VIDEO_MAX_MB=250\n'
    printf 'MIN_FREE_MB=1024\n'
    printf 'OLLAMA_BASE_URL=http://127.0.0.1:11434\n'
    printf 'OLLAMA_MODEL=qwen2.5:0.5b\n'
    printf 'OLLAMA_VISION_MODEL=moondream:1.8b\n'
    printf 'OLLAMA_VISION_ENABLED=false\n'
    printf 'OLLAMA_TIMEOUT_SECONDS=45\n'
    printf 'FAIRY_AUTO_COMMENT=false\n'
  } > "$environment_file"
fi

sed -e "s|/home/jetson/fairy_lan|$project_dir|g" \
    -e "s|^User=jetson$|User=$service_user|" \
    -e "s|^Group=jetson$|Group=$service_group|" \
    "$service_source" > /etc/systemd/system/virgozone.service
chmod 0644 /etc/systemd/system/virgozone.service
install -m 0644 "$avahi_source" /etc/avahi/services/virgozone-http.service
runuser -u "$service_user" -- "$project_dir/.venv/bin/python" "$project_dir/scripts/import_schedule.py"

if [[ -f "$avahi_config" ]]; then
  if [[ ! -f "${avahi_config}.before-virgozone" ]]; then
    cp -a "$avahi_config" "${avahi_config}.before-virgozone"
  fi
  if grep -qE '^[# ]*host-name=' "$avahi_config"; then
    sed -i -E 's/^[# ]*host-name=.*/host-name=virgozone/' "$avahi_config"
  else
    sed -i '/^\[server\]$/a host-name=virgozone' "$avahi_config"
  fi
fi

systemctl daemon-reload
systemctl enable --now avahi-daemon.service
systemctl restart avahi-daemon.service
systemctl enable --now virgozone.service

echo
echo "VirgoZone service installed."
echo "Open: http://virgozone.local:8080"
echo "Status: systemctl status virgozone --no-pager"
echo "Logs: journalctl -u virgozone -f"
