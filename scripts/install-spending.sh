#!/usr/bin/env bash
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV_BIN="${ROOT}/.venv/bin"
LAUNCHER="${ROOT}/spending.py"

mkdir -p "${VENV_BIN}"
cat > "${VENV_BIN}/spending" << EOF
#!/usr/bin/env bash
exec "${VENV_BIN}/python" "${LAUNCHER}" "\$@"
EOF
chmod +x "${VENV_BIN}/spending"
echo "Installed: ${VENV_BIN}/spending"
