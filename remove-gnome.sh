#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# GNOME Removal Script for Debian-Niri
# ──────────────────────────────────────────────────────────────────────────────
#
# Removes GNOME desktop environment from a Debian system.
# Designed to be run BEFORE the Niri installer on a Debian system that
# comes pre-installed with GNOME (e.g., Debian with desktop environment).
#
# Usage:
#   su -
#   ./remove-gnome.sh
#   reboot
#   ./install.sh          # Now install Niri + Noctalia
#
# ──────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# ── Colors ─────────────────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()   { echo -e "${BLUE}::${NC} ${BOLD}$1${NC}"; }
ok()     { echo -e "${GREEN}==>${NC} $1"; }
warn()   { echo -e "${YELLOW}!!${NC} $1"; }
die()    { echo -e "${RED}!!${NC} $1" >&2; exit 1; }
header() { echo; echo -e "${CYAN}════════════════════════════════════════════════════════════════${NC}"; echo -e "${CYAN}  $1${NC}"; echo -e "${CYAN}════════════════════════════════════════════════════════════════${NC}"; echo; }

# ── Pre-flight Checks ──────────────────────────────────────────────────────────

header "Pre-flight Checks"

if [ "$(id -u)" -ne 0 ]; then
    die "This script must be run as root.\n  su -\n  ./remove-gnome.sh"
fi
ok "Running as root"

# Warn about what we're about to do
echo
echo -e "${YELLOW}⚠  This will remove GNOME desktop environment and all its components.${NC}"
echo -e "${YELLOW}⚠  The system will switch to a minimal (TTY-only) state.${NC}"
echo -e "${YELLOW}⚠  After this, run install.sh to install Niri + Noctalia.${NC}"
echo
echo -n -e "${BOLD}Continue? [y/N] ${NC}"
read -r CONFIRM
if [ "${CONFIRM}" != "y" ] && [ "${CONFIRM}" != "Y" ]; then
    die "Aborted by user."
fi

# ── Stop GDM3 First ────────────────────────────────────────────────────────────

header "Stopping Display Manager"

if systemctl is-active gdm3 >/dev/null 2>&1; then
    info "Stopping gdm3..."
    systemctl stop gdm3
    ok "gdm3 stopped"
fi

if systemctl is-enabled gdm3 >/dev/null 2>&1; then
    info "Disabling gdm3..."
    systemctl disable gdm3
    ok "gdm3 disabled"
fi

# ── Remove GNOME Packages ──────────────────────────────────────────────────────

header "Removing GNOME Packages"

GNOME_PACKAGES=(
    # Core GNOME
    gnome
    gnome-core
    gnome-shell
    gnome-session
    gnome-session-bin
    gnome-control-center
    gnome-settings-daemon
    gnome-shell-common
    gnome-user-share

    # GNOME Apps
    gnome-software
    gnome-software-common
    gnome-terminal
    gnome-terminal-data
    gnome-backgrounds
    gnome-bluetooth
    gnome-calculator
    gnome-calendar
    gnome-characters
    gnome-clocks
    gnome-contacts
    gnome-disk-utility
    gnome-font-viewer
    gnome-keyring
    gnome-logs
    gnome-maps
    gnome-menus
    gnome-music
    gnome-remote-desktop
    gnome-screenshot
    gnome-system-monitor
    gnome-text-editor
    gnome-weather
    gnome-user-docs

    # Display Manager
    gdm3

    # Compositor
    mutter

    # File Manager
    nautilus
    nautilus-extension-gnome-terminal
    nautilus-sendto

    # Indexing / Search
    tracker
    tracker3
    tracker-miner-fs
    tracker-extract

    # Email / Calendar
    evolution
    evolution-data-server
    evolution-common

    # Portals (KEEP — required by Niri for file dialogs and portal functionality)
    # xdg-desktop-portal-gnome  ← DO NOT REMOVE
    # xdg-desktop-portal-gtk     ← DO NOT REMOVE

    # GNOME Keyring (KEEP — required for SSH keys, password storage)
    # gnome-keyring              ← DO NOT REMOVE

    # Apps
    shotwell
    simple-scan
    sushi
    yelp
    totem
    eog
    seahorse
    file-roller

    # Misc GNOME dependencies
    gnome-desktop3-data
    gnome-desktop-common
    gnome-video-effects
    gnome-online-accounts
    gnome-online-accounts-gtk

    # NetworkManager GNOME (KEEP — provides nm-applet for network management)
    # network-manager-gnome     ← DO NOT REMOVE

    # Power management
    power-profiles-daemon
)

info "Purging ${#GNOME_PACKAGES[@]} GNOME packages..."
DEBIAN_FRONTEND=noninteractive apt purge -y "${GNOME_PACKAGES[@]}" 2>/dev/null || true

# ── Remove Orphaned Dependencies ────────────────────────────────────────────────

header "Cleaning Up"

info "Removing orphaned dependencies..."
apt autoremove -y --purge 2>/dev/null || true

info "Cleaning apt cache..."
apt autoclean 2>/dev/null || true
apt clean 2>/dev/null || true

# ── Remove GNOME Configuration ─────────────────────────────────────────────────

header "Removing Configuration Files"

# System configs
rm -rf /etc/gdm3 2>/dev/null || true
rm -rf /var/lib/gdm3 2>/dev/null || true
rm -rf /usr/share/gnome-shell 2>/dev/null || true
rm -rf /usr/lib/gdm3 2>/dev/null || true
rm -rf /etc/xdg/gnome 2>/dev/null || true
rm -rf /etc/gnome 2>/dev/null || true

# User configs
for HOME_DIR in /home/*; do
    [ -d "${HOME_DIR}" ] || continue

    echo "  Cleaning: ${HOME_DIR}"

    # Config directories
    rm -rf "${HOME_DIR}/.config/gnome-shell" 2>/dev/null || true
    rm -rf "${HOME_DIR}/.config/gnome-session" 2>/dev/null || true
    rm -rf "${HOME_DIR}/.config/nautilus" 2>/dev/null || true
    rm -rf "${HOME_DIR}/.config/evolution" 2>/dev/null || true
    rm -rf "${HOME_DIR}/.config/gnome-control-center" 2>/dev/null || true
    rm -rf "${HOME_DIR}/.config/gnome-settings-daemon" 2>/dev/null || true

    # Local data
    rm -rf "${HOME_DIR}/.local/share/gnome-shell" 2>/dev/null || true
    rm -rf "${HOME_DIR}/.local/share/nautilus" 2>/dev/null || true
    rm -rf "${HOME_DIR}/.local/share/evolution" 2>/dev/null || true

    # Cache
    rm -rf "${HOME_DIR}/.cache/gnome-shell" 2>/dev/null || true
    rm -rf "${HOME_DIR}/.cache/nautilus" 2>/dev/null || true
    rm -rf "${HOME_DIR}/.cache/evolution" 2>/dev/null || true

    # GTK bookmarks (will be recreated by Niri installer)
    rm -f "${HOME_DIR}/.config/gtk-3.0/bookmarks" 2>/dev/null || true

    # Desktop background configs
    rm -f "${HOME_DIR}/.config/pulse/default.pa" 2>/dev/null || true

    # dconf (GNOME settings database — this is the big one)
    rm -rf "${HOME_DIR}/.config/dconf" 2>/dev/null || true
done

# Remove root's GNOME configs too
rm -rf /root/.config/gnome-shell 2>/dev/null || true
rm -rf /root/.local/share/gnome-shell 2>/dev/null || true
rm -rf /root/.cache/gnome-shell 2>/dev/null || true
rm -rf /root/.config/dconf 2>/dev/null || true

# ── Verify Removal ──────────────────────────────────────────────────────────────

header "Verification"

REMAINING=$(dpkg -l 2>/dev/null | grep -c '^ii.*gnome-' || true)
if [ "${REMAINING}" -gt 0 ]; then
    warn "${REMAINING} gnome-* packages still remain"
    echo "  Run: apt purge 'gnome-*' to remove them"
else
    ok "No gnome-* packages remain"
fi

if systemctl is-enabled gdm3 >/dev/null 2>&1; then
    warn "gdm3 is still enabled"
else
    ok "gdm3 is disabled"
fi

# ── Final Message ───────────────────────────────────────────────────────────────

echo
echo -e "${GREEN}════════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  ✅ GNOME REMOVED${NC}"
echo -e "${GREEN}════════════════════════════════════════════════════════════════${NC}"
echo
echo -e "  ${BOLD}Next steps:${NC}"
echo "    1. Reboot:  sudo reboot"
echo "    2. Clone:   git clone https://github.com/Redm00use/Debian-Niri.git"
echo "    3. Install: cd Debian-Niri && sudo ./install.sh"
echo
echo -e "  ${BOLD}Manual check:${NC}"
echo "    systemctl status greetd"
echo "    which niri"
echo "    systemctl --user status noctalia-shell"
echo
