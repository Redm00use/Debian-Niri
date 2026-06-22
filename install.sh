#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# Nixdots → Debian Migration — Bootstrap Script
# ──────────────────────────────────────────────────────────────────────────────
#
# Usage:
#   chmod +x install.sh
#   sudo ./install.sh
#   sudo ./install.sh --dry-run        # Preview without changes
#   sudo ./install.sh --system-only    # System packages only
#   sudo ./install.sh --skip-upgrade   # Skip apt upgrade
#
# This script:
#   1. Verifies Debian OS, root access, and internet connectivity.
#   2. Installs all packages required to run the Python installer.
#   3. Creates a Python virtual environment with dependencies.
#   4. Launches installer/install.py with all arguments forwarded.
#
# Log: install.log in the current directory.
#
# ──────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# ── Configuration ──────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALLER="${SCRIPT_DIR}/installer/install.py"
LOG_FILE="${SCRIPT_DIR}/install.log"
REQUIREMENTS="${SCRIPT_DIR}/requirements.txt"
VENV_DIR="${SCRIPT_DIR}/.venv"

MIN_PYTHON_MAJOR=3
MIN_PYTHON_MINOR=10

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# ── Logging ────────────────────────────────────────────────────────────────────

# Truncate log file on first run
: > "${LOG_FILE}"

log() {
    local level="$1"
    local msg="$2"
    local timestamp
    timestamp="$(date '+%Y-%m-%d %H:%M:%S')"
    echo "[${timestamp}] [${level}] ${msg}" >> "${LOG_FILE}"
}

info()   { echo -e "${BLUE}::${NC} ${BOLD}$1${NC}"; log "INFO" "$1"; }
ok()     { echo -e "${GREEN}==>${NC} $1";           log "OK" "$1"; }
warn()   { echo -e "${YELLOW}!!${NC} $1";           log "WARN" "$1"; }
fail()   { echo -e "${RED}!!${NC} $1" >&2;          log "FAIL" "$1"; }
die()    { fail "$1"; exit 1; }
header() { echo; echo -e "${CYAN}════════════════════════════════════════════════════════════════${NC}"; echo -e "${CYAN}  $1${NC}"; echo -e "${CYAN}════════════════════════════════════════════════════════════════${NC}"; echo; }

# ── Error Handler ──────────────────────────────────────────────────────────────

trap 'echo -e "\n${RED}✖ Bootstrap failed at line $LINENO. See ${LOG_FILE} for details.${NC}"' ERR

# ── Argument Parsing ───────────────────────────────────────────────────────────

DRY_RUN=""
SKIP_UPGRADE=""
INSTALLER_ARGS=()

for arg in "$@"; do
    case "${arg}" in
        --dry-run)
            DRY_RUN="1"
            INSTALLER_ARGS+=("${arg}")
            ;;
        --skip-upgrade)
            SKIP_UPGRADE="1"
            ;;
        *)
            INSTALLER_ARGS+=("${arg}")
            ;;
    esac
done

# ── Stage 0: Self-test ─────────────────────────────────────────────────────────

header "Stage 0: Self-Test"

# 0a. Check that install.py exists
if [ ! -f "${INSTALLER}" ]; then
    die "Installer not found at ${INSTALLER}. Are you in the project root?"
fi
ok "Installer found: ${INSTALLER}"

# 0b. Detect dry-run
if [ -n "${DRY_RUN}" ]; then
    info "Dry-run mode enabled. No system changes will be made."
fi

# ── Stage 1: Verify Environment ────────────────────────────────────────────────

header "Stage 1: Environment Verification"

# 1a. OS check
if [ ! -f /etc/os-release ]; then
    die "Cannot detect operating system. /etc/os-release not found."
fi

OS_ID="$(grep -oP '^ID=\K.*' /etc/os-release 2>/dev/null || echo "unknown")"
OS_VERSION="$(grep -oP '^VERSION_ID=\K.*' /etc/os-release 2>/dev/null || echo "unknown")"

info "Detected OS: ${OS_ID} ${OS_VERSION}"

case "${OS_ID}" in
    debian|ubuntu)
        ok "Supported OS: ${OS_ID}"
        ;;
    *)
        die "Unsupported OS: ${OS_ID}. This installer targets Debian."
        ;;
esac

# 1b. Root / sudo check
if [ "$(id -u)" -ne 0 ]; then
    die "This script must be run as root. Use: sudo ./install.sh"
fi
ok "Running as root"

# 1c. Internet connectivity check
info "Checking internet connectivity..."
if command -v curl &>/dev/null; then
    if curl -s --connect-timeout 5 --max-time 10 https://deb.debian.org >/dev/null 2>&1; then
        ok "Internet connectivity verified (Debian repo reachable)"
    elif curl -s --connect-timeout 5 --max-time 10 https://github.com >/dev/null 2>&1; then
        ok "Internet connectivity verified (GitHub reachable)"
    else
        warn "Internet connectivity check failed. Continuing anyway..."
    fi
elif command -v wget &>/dev/null; then
    if wget -q --timeout=10 --tries=1 -O /dev/null https://deb.debian.org >/dev/null 2>&1; then
        ok "Internet connectivity verified (Debian repo reachable)"
    else
        warn "Internet connectivity check failed. Continuing anyway..."
    fi
else
    warn "Neither curl nor wget available for connectivity check. Continuing..."
fi

# 1d. Check shell
if [ "${SHELL:-}" = "" ] && [ -z "${DRY_RUN}" ]; then
    warn "SHELL variable not set. The installer will set Zsh as the user shell."
fi

# ── Stage 2: System Update ─────────────────────────────────────────────────────

header "Stage 2: System Update"

if [ -n "${SKIP_UPGRADE}" ]; then
    info "Skipping apt upgrade (--skip-upgrade flag detected)"
else
    info "Updating package lists..."
    if [ -z "${DRY_RUN}" ]; then
        apt-get update -qq 2>&1 | tee -a "${LOG_FILE}"
        ok "Package lists updated"
    else
        info "[dry-run] Would run: apt-get update"
    fi

    info "Upgrading installed packages..."
    if [ -z "${DRY_RUN}" ]; then
        apt-get upgrade -y -qq 2>&1 | tee -a "${LOG_FILE}"
        ok "System packages upgraded"
    else
        info "[dry-run] Would run: apt-get upgrade -y"
    fi
fi

# ── Stage 3: Install Build Dependencies ────────────────────────────────────────

header "Stage 3: Installing Build Dependencies"

PACKAGES=(
    # Python (required to run the installer)
    python3
    python3-pip
    python3-venv
    python3-dev

    # Git (for cloning Vimix-cursors theme)
    git

    # Download tools
    curl
    wget
    ca-certificates

    # Build tools (for compiling Niri, Yazi, Eww, etc.)
    build-essential
    pkg-config
    cmake

    # Rust (for Niri, Yazi, Eww, Sunder)
    rustc
    cargo

    # Go (for Walker, Elephant)
    golang-go

    # Node.js / npm (for WezTerm, Cider builds)
    nodejs
    npm

    # Library headers (for cargo builds)
    libgtk-3-dev
    libwebkit2gtk-4.1-dev
    libayatana-appindicator3-dev
    libsoup-3.0-dev
    libjavascriptcoregtk-4.1-dev
)

info "Installing ${#PACKAGES[@]} packages..."
if [ -z "${DRY_RUN}" ]; then
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${PACKAGES[@]}" 2>&1 | tee -a "${LOG_FILE}"
    ok "Build dependencies installed"
else
    info "[dry-run] Would install packages: ${PACKAGES[*]}"
fi

# ── Stage 4: Python Virtual Environment ────────────────────────────────────────

header "Stage 4: Python Virtual Environment"

if [ -z "${DRY_RUN}" ]; then
    # Check Python version
    PYTHON_BIN=""
    for candidate in python3 python3.12 python3.11 python3.10; do
        if command -v "${candidate}" &>/dev/null; then
            PYTHON_BIN="${candidate}"
            break
        fi
    done

    if [ -z "${PYTHON_BIN}" ]; then
        die "Python 3 not found. Install python3 and try again."
    fi

    PYTHON_VERSION="$("${PYTHON_BIN}" --version 2>&1 | grep -oP '\d+\.\d+')"
    PYTHON_MAJOR="$(echo "${PYTHON_VERSION}" | cut -d. -f1)"
    PYTHON_MINOR="$(echo "${PYTHON_VERSION}" | cut -d. -f2)"

    info "Python version: $("${PYTHON_BIN}" --version 2>&1)"

    if [ "${PYTHON_MAJOR}" -lt "${MIN_PYTHON_MAJOR}" ] || \
       { [ "${PYTHON_MAJOR}" -eq "${MIN_PYTHON_MAJOR}" ] && [ "${PYTHON_MINOR}" -lt "${MIN_PYTHON_MINOR}" ]; }; then
        die "Python ${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR}+ required (found ${PYTHON_VERSION})"
    fi
    ok "Python version meets minimum requirement (>= ${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR})"

    # Create virtual environment
    if [ -d "${VENV_DIR}" ]; then
        info "Virtual environment already exists at ${VENV_DIR}"
        # Check if it's valid
        if [ ! -f "${VENV_DIR}/bin/activate" ]; then
            warn "Existing .venv is incomplete. Recreating..."
            rm -rf "${VENV_DIR}"
            "${PYTHON_BIN}" -m venv "${VENV_DIR}"
            ok "Virtual environment recreated"
        else
            ok "Using existing virtual environment"
        fi
    else
        info "Creating virtual environment..."
        "${PYTHON_BIN}" -m venv "${VENV_DIR}"
        ok "Virtual environment created at ${VENV_DIR}"
    fi

    # Activate virtual environment
    # shellcheck source=/dev/null
    source "${VENV_DIR}/bin/activate"
    ok "Virtual environment activated"

    # Install Python dependencies
    if [ -f "${REQUIREMENTS}" ]; then
        # Check if requirements.txt has actual entries (non-comment, non-blank)
        if grep -q -v '^\s*#\|^\s*$' "${REQUIREMENTS}" 2>/dev/null; then
            info "Installing Python dependencies from requirements.txt..."
            pip install --quiet --upgrade pip 2>&1 | tee -a "${LOG_FILE}"
            pip install --quiet -r "${REQUIREMENTS}" 2>&1 | tee -a "${LOG_FILE}"
            ok "Python dependencies installed"
        else
            info "requirements.txt contains no installable packages (stdlib only). Skipping pip install."
        fi
    else
        info "requirements.txt not found. Skipping pip install."
    fi

    # Ensure pip is available (even without requirements)
    if ! command -v pip &>/dev/null; then
        "${PYTHON_BIN}" -m ensurepip --upgrade 2>&1 | tee -a "${LOG_FILE}" || true
    fi
else
    info "[dry-run] Would create Python virtual environment at ${VENV_DIR}"
fi

# ── Stage 5: Launch Installer ──────────────────────────────────────────────────

header "Stage 5: Launching Installer"

if [ -z "${DRY_RUN}" ]; then
    info "Launching: ${INSTALLER} ${INSTALLER_ARGS[*]}"
    echo

    # shellcheck source=/dev/null
    source "${VENV_DIR}/bin/activate"

    if python3 "${INSTALLER}" "${INSTALLER_ARGS[@]}" 2>&1 | tee -a "${LOG_FILE}"; then
        echo
        echo -e "${GREEN}════════════════════════════════════════════════════════════════${NC}"
        echo -e "${GREEN}  ✅ INSTALLATION COMPLETE${NC}"
        echo -e "${GREEN}  Log: ${LOG_FILE}${NC}"
        echo -e "${GREEN}════════════════════════════════════════════════════════════════${NC}"
        echo
        echo -e "  ${BOLD}Next steps:${NC}"
        echo "    1. Reboot: sudo reboot"
        echo "    2. greetd + tuigreet will present a login prompt"
        echo "    3. Log in as 'kotlin' (password: 1408)"
        echo "    4. Niri + Noctalia desktop starts automatically"
        echo
        echo -e "  ${BOLD}Manual steps remaining:${NC}"
        echo "    - Noctalia Shell source build (see README.md)"
        echo "    - Quickshell build (see README.md)"
        echo "    - Neovim config: git clone https://github.com/viitorags/nvim ~/.config/nvim"
        echo
        exit 0
    else
        echo
        echo -e "${RED}════════════════════════════════════════════════════════════════${NC}"
        echo -e "${RED}  ❌ INSTALLATION FAILED${NC}"
        echo -e "${RED}  See ${LOG_FILE} for details.${NC}"
        echo -e "${RED}════════════════════════════════════════════════════════════════${NC}"
        echo
        echo -e "  ${BOLD}Common fixes:${NC}"
        echo "    1. Check network connectivity"
        echo "    2. Ensure sufficient disk space"
        echo "    3. Check install.log for specific errors"
        echo "    4. Re-run: sudo ./install.sh"
        echo
        exit 1
    fi
else
    info "[dry-run] Would launch: python3 ${INSTALLER} ${INSTALLER_ARGS[*]}"
    echo
    echo -e "${YELLOW}════════════════════════════════════════════════════════════════${NC}"
    echo -e "${YELLOW}  ✅ DRY RUN COMPLETE — No changes were made.${NC}"
    echo -e "${YELLOW}  Run without --dry-run to apply changes.${NC}"
    echo -e "${YELLOW}════════════════════════════════════════════════════════════════${NC}"
    echo
fi
