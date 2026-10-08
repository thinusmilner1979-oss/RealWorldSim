#!/usr/bin/env bash
# Install RealWorldSim on Linux Mint / Ubuntu: venv in ~/.local/share/realworldsim, desktop launcher.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${HOME}/.local/share/realworldsim/venv"

if ! command -v python3 >/dev/null; then echo "python3 is required (sudo apt install python3 python3-venv)"; exit 1; fi
python3 - <<'PY' || { echo "Python 3.11+ required"; exit 1; }
import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)
PY

echo "creating venv at $VENV"
python3 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip >/dev/null
"$VENV/bin/pip" install -e "$HERE"

mkdir -p "${HOME}/.local/bin" "${HOME}/.local/share/applications" "${HOME}/.local/share/realworldsim"
cat > "${HOME}/.local/bin/realworldsim" <<SH
#!/usr/bin/env bash
cd "${HOME}/.local/share/realworldsim"
exec "$VENV/bin/rws" serve "\$@"
SH
chmod +x "${HOME}/.local/bin/realworldsim"
# `rws` from any terminal (runs inside the venv; data and saves live in the app dir)
cat > "${HOME}/.local/bin/rws" <<SH
#!/usr/bin/env bash
cd "${HOME}/.local/share/realworldsim"
exec "$VENV/bin/rws" "\$@"
SH
chmod +x "${HOME}/.local/bin/rws"

cat > "${HOME}/.local/share/applications/realworldsim.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=RealWorldSim
Comment=A probabilistic world model
Exec=${HOME}/.local/bin/realworldsim
Icon=applications-science
Terminal=true
Categories=Science;Education;Simulation;
DESK
update-desktop-database "${HOME}/.local/share/applications" 2>/dev/null || true

echo
echo "Installed. Launch from the menu (RealWorldSim), or in a terminal:"
echo "  rws serve        web UI on http://127.0.0.1:8050"
echo "  rws sync         pull today's data (World Bank, UCDP, GDELT, FRED)"
echo "  rws backtest     score the model against 2015-2025"
echo "Data cache, saves and backtest reports live in ${HOME}/.local/share/realworldsim"
case ":$PATH:" in
  *":${HOME}/.local/bin:"*) ;;
  *) echo; echo "NOTE: ${HOME}/.local/bin is not on your PATH yet. Open a new terminal (Mint adds it"
     echo "      automatically at login) or run:  export PATH=\"\$HOME/.local/bin:\$PATH\"";;
esac
