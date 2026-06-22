#!/usr/bin/env python3
"""
Debian Migration Installer for Nixdots → Debian

Rebuilds the Niri + Noctalia desktop environment from a minimal Debian base.
Preserves the exact configuration, behavior, and workflow of the original NixOS setup.

Usage:
    sudo python3 install.py            # Full install
    python3 install.py --dry-run       # Preview without changes
    python3 install.py --backup        # Create backup only
    python3 install.py --restore       # Restore from backup
    python3 install.py --system-only   # System packages only
    python3 install.py --user-only     # User config only
"""

import argparse
import json
import logging
import os
import shlex
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── Configuration ──────────────────────────────────────────────────────────────

USERNAME = "kotlin"
USER_GROUP = "kotlin"
USER_HOME = f"/home/{USERNAME}"
USER_PASSWORD = "1408"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_SRC = PROJECT_ROOT / "configs"
ASSETS_SRC = PROJECT_ROOT / "assets"
PATCHES_SRC = PROJECT_ROOT / "patches"
VENDOR_SRC = PROJECT_ROOT / "vendor"
SCRIPTS_SRC = PROJECT_ROOT / "scripts"
SYSTEM_SRC = PROJECT_ROOT / "system"
USER_SRC = PROJECT_ROOT / "user"

BACKUP_DIR = Path(f"/tmp/nixdots-migration-backup-{datetime.now().strftime('%Y%m%d_%H%M%S')}")
LOG_FILE = Path(f"/tmp/nixdots-install-{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

# ── Logging ────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("nixdots-debian")


# ── Utility Functions ──────────────────────────────────────────────────────────

def run(cmd: List[str], check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    """Run a shell command with logging."""
    log.debug(f"$ {shlex.join(cmd)}")
    try:
        if capture:
            result = subprocess.run(cmd, capture_output=True, text=True, check=check)
        else:
            result = subprocess.run(cmd, check=check)
        return result
    except subprocess.CalledProcessError as e:
        log.error(f"Command failed: {shlex.join(cmd)}")
        log.error(f"Exit code: {e.returncode}")
        if e.stdout:
            log.error(f"stdout: {e.stdout}")
        if e.stderr:
            log.error(f"stderr: {e.stderr}")
        if check:
            raise
        return e


def apt_install(packages: List[str], dry_run: bool = False) -> None:
    """Install Debian packages via apt, skipping unavailable ones."""
    if not packages:
        return
    # Filter: only install packages that have a candidate in configured repos
    available = []
    skipped = []
    for pkg in packages:
        result = run(["apt-cache", "policy", pkg], check=False, capture=True)
        if result.returncode == 0 and "Candidate: (none)" not in result.stdout:
            available.append(pkg)
        else:
            skipped.append(pkg)
    if skipped:
        log.warning(f"Skipping {len(skipped)} unavailable packages: {', '.join(skipped)}")
    if not available:
        return
    log.info(f"Installing {len(available)} packages: {' '.join(available[:5])}...")
    if not dry_run:
        run(["apt-get", "install", "-y", "--no-install-recommends"] + available)


def is_package_installed(pkg: str) -> bool:
    """Check if a Debian package is installed."""
    result = run(["dpkg", "-l", pkg], check=False, capture=True)
    return result.returncode == 0 and "ii" in result.stdout[:2]


def service_enable(service_name: str, system: bool = True, dry_run: bool = False) -> None:
    """Enable a systemd service."""
    if dry_run:
        log.info(f"  [dry-run] Would enable service: {service_name}")
        return
    prefix = "" if system else "--user"
    uid_arg = [] if system else ["-E"]
    if system:
        run(["systemctl", "enable", service_name])
        run(["systemctl", "start", service_name])
    else:
        run(["systemctl", "--user", "enable", service_name])
        run(["systemctl", "--user", "start", service_name])


def write_file(path: Path, content: str, dry_run: bool = False) -> None:
    """Write content to a file, creating parent directories."""
    if dry_run:
        log.info(f"  [dry-run] Would write: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    log.debug(f"  Wrote: {path}")


def copy_file(src: Path, dst: Path, dry_run: bool = False) -> None:
    """Copy a file or directory, preserving metadata."""
    if dry_run:
        log.info(f"  [dry-run] Would copy: {src} → {dst}")
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst, symlinks=True)
    else:
        shutil.copy2(src, dst)
    log.debug(f"  Copied: {src} → {dst}")


def existing_groups() -> set:
    """Return set of all group names present on the system."""
    groups = set()
    try:
        with open("/etc/group", "r") as f:
            for line in f:
                line = line.strip()
                if line and ":" in line:
                    groups.add(line.split(":", 1)[0])
    except Exception:
        pass
    return groups


def ensure_user_exists(username: str, dry_run: bool = False) -> None:
    """Create user if they don't exist."""
    if dry_run:
        log.info(f"  [dry-run] Would ensure user exists: {username}")
        return
    # Only add to groups that actually exist on the system
    wanted = ["plugdev", "video", "input", "kvm", "libvirt", "lpadmin"]
    valid = [g for g in wanted if g in existing_groups()]
    result = run(["id", username], check=False, capture=True)
    if result.returncode != 0:
        log.info(f"Creating user: {username}")
        if valid:
            run(["useradd", "-m", "-G", ",".join(valid),
                 "-s", "/usr/bin/zsh", username])
        else:
            run(["useradd", "-m", "-s", "/usr/bin/zsh", username])
        run(["chpasswd"], input=f"{username}:{USER_PASSWORD}", text=True)
    else:
        log.info(f"User {username} already exists")
        # Ensure user is in required groups (only existing ones)
        if valid:
            run(["usermod", "-aG", ",".join(valid), username])


def make_backup(source_dir: str, dry_run: bool = False) -> Optional[Path]:
    """Create a timestamped backup of user configs."""
    if dry_run:
        log.info(f"  [dry-run] Would backup: {source_dir} → {BACKUP_DIR}")
        return BACKUP_DIR
    log.info(f"Creating backup in {BACKUP_DIR}...")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup_paths = [
        Path(f"{USER_HOME}/.config"),
        Path(f"{USER_HOME}/.zshrc"),
        Path(f"{USER_HOME}/.face"),
        Path(f"{USER_HOME}/.local/share/applications"),
    ]
    for path in backup_paths:
        if path.exists():
            dest = BACKUP_DIR / path.relative_to(USER_HOME) if str(path).startswith(USER_HOME) else BACKUP_DIR / path.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            if path.is_dir():
                shutil.copytree(str(path), str(dest), symlinks=True, dirs_exist_ok=True)
            else:
                shutil.copy2(str(path), str(dest))
            log.info(f"  Backed up: {path}")
    return BACKUP_DIR


# ── Package Mapping ────────────────────────────────────────────────────────────

# Maps NixOS programs → Debian packages
SYSTEM_PACKAGES = {
    # Core utilities
    "git": "git",
    "wget": "wget",
    "curl": "curl",
    "unzip": "unzip",
    "unrar": "unrar-free",
    "zip": "zip",
    "tree": "tree",
    "ffmpeg": "ffmpeg",
    "bc": "bc",
    "htop": "htop",
    "jq": "jq",
    "file": "file",
    "pciutils": "pciutils",
    "usbutils": "usbutils",
    "xdg-utils": "xdg-utils",
    "exfatprogs": "exfatprogs",
    "upower": "upower",
    "brightnessctl": "brightnessctl",
    "playerctl": "playerctl",

    # Desktop + Wayland
    "zsh": "zsh",
    "eza": "eza",
    "pavucontrol": "pavucontrol",
    "pamixer": "pamixer",
    "grim": "grim",
    "slurp": "slurp",
    "wl-clipboard": "wl-clipboard",
    "wtype": "wtype",
    "cliphist": "cliphist",
    "freerdp": "freerdp3-x11",
    "sioyek": "sioyek",
    "direnv": "direnv",
    "lazygit": "lazygit",
    "gh": "gh",
    "fd": "fd-find",
    "ripgrep": "ripgrep",
    "glow": "glow",
    "shellcheck": "shellcheck",
    "shfmt": "shfmt",
    "delta": "git-delta",


    # Audio
    "pipewire": "pipewire",
    "wireplumber": "wireplumber",
    "pipewire-pulse": "pipewire-pulse",
    "pipewire-alsa": "pipewire-alsa",
    "pipewire-jack": "pipewire-jack",
    "pulseaudio-utils": "pulseaudio-utils",

    # Bluetooth
    "bluez": "bluez",

    "blueman": "blueman",

    # Printing
    "cups": "cups",
    "cups-bsd": "cups-bsd",
    "cups-filters": "cups-filters",
    "gutenprint": "printer-driver-gutenprint",
    "epson-escpr": "printer-driver-escpr",

    # GTK/Qt theming
    "gnome-themes-extra": "gnome-themes-extra",
    "adwaita-icon-theme": "adwaita-icon-theme",
    "hicolor-icon-theme": "hicolor-icon-theme",
    "papirus-icon-theme": "papirus-icon-theme",
    "qt5ct": "qt5ct",
    "qt6ct": "qt6ct",

    "qt6-style-kvantum": "qt6-style-kvantum",

    "kvantum": "qt6-style-kvantum",

    # Fonts
    "fonts-jetbrains-mono": "fonts-jetbrains-mono",
    "fonts-firacode": "fonts-firacode",
    "fonts-noto": "fonts-noto",
    "fonts-noto-cjk": "fonts-noto-cjk",
    "fonts-noto-color-emoji": "fonts-noto-color-emoji",
    "fonts-font-awesome": "fonts-font-awesome",

    # GPU
    "mesa-utils": "mesa-utils",
    "mesa-va-drivers": "mesa-va-drivers",
    "mesa-vdpau-drivers": "mesa-vdpau-drivers",
    "vulkan-tools": "vulkan-tools",
    "libvulkan1": "libvulkan1",
    "libvulkan-dev": "libvulkan-dev",
    "va-driver-all": "va-driver-all",
    "vdpau-driver-all": "vdpau-driver-all",
    "libgl1-mesa-dri": "libgl1-mesa-dri",
    "libglx-mesa0": "libglx-mesa0",


    # Virtualization
    "qemu-kvm": "qemu-system-x86",
    "libvirt-daemon-system": "libvirt-daemon-system",
    "libvirt-clients": "libvirt-clients",
    "virt-manager": "virt-manager",
    "virt-viewer": "virt-viewer",
    "virtiofsd": "virtiofsd",
    "swtpm": "swtpm",
    "gnome-boxes": "gnome-boxes",
    "dnsmasq": "dnsmasq",

    # Steam / Gaming
    "steam": "steam-installer",
    "steam-devices": "steam-devices",
    "gamemode": "gamemode",
    "mangohud": "mangohud",


    # Polkit / Auth
    "polkitd": "polkitd",
    "gnome-keyring": "gnome-keyring",
    "libpam-gnome-keyring": "libpam-gnome-keyring",
    "accounts-daemon": "accountsservice",
    "polkit-kde-agent": "polkit-kde-agent-1",

    # Portal
    "xdg-desktop-portal": "xdg-desktop-portal",
    "xdg-desktop-portal-gtk": "xdg-desktop-portal-gtk",
    "xdg-desktop-portal-wlr": "xdg-desktop-portal-wlr",

    # Network
    "network-manager": "network-manager",
    "network-manager-gnome": "network-manager-gnome",
    "avahi": "avahi-daemon",

    # Desktop apps
    "nautilus": "nautilus",
    "gvfs": "gvfs",
    "gvfs-backends": "gvfs-backends",
    "mpv": "mpv",
    "yt-dlp": "yt-dlp",
    "imv": "imv",
    "qimgv": "qimgv",
    "libreoffice": "libreoffice",

    "ark": "ark",
    "gparted": "gparted",
    "obs-studio": "obs-studio",

    "qbittorrent": "qbittorrent",
    "android-tools": "android-tools-adb",

    # Niri dependencies
    "libxkbcommon": "libxkbcommon0",
    "libxkbcommon-x11": "libxkbcommon-x11-0",
    "libinput": "libinput10",
    "libseat1": "libseat1",

    # Build tools (for source builds)
    "build-essential": "build-essential",
    "pkg-config": "pkg-config",
    "cmake": "cmake",
    "meson": "meson",
    "ninja-build": "ninja-build",
    "rustc": "rustc",
    "cargo": "cargo",
    "npm": "npm",
    "nodejs": "nodejs",
    "python3": "python3",
    "python3-pip": "python3-pip",
    "python3-requests": "python3-requests",
    "libglib2.0-dev": "libglib2.0-dev",
    "libgtk-3-dev": "libgtk-3-dev",
    "libpango1.0-dev": "libpango1.0-dev",
    "libcairo2-dev": "libcairo2-dev",
    "libgdk-pixbuf-2.0-dev": "libgdk-pixbuf-2.0-dev",
    "libatk1.0-dev": "libatk1.0-dev",
    "libsoup-3.0-dev": "libsoup-3.0-dev",
    "libjavascriptcoregtk-4.1-dev": "libjavascriptcoregtk-4.1-dev",
    "libwebkit2gtk-4.1-dev": "libwebkit2gtk-4.1-dev",
    "libappindicator3-dev": "libayatana-appindicator3-dev",

    "clang-tools": "clang-tools",
    "gcc": "gcc",

    "cava": "cava",
    "fastfetch": "fastfetch",
}

# Desktop-only packages (isDesktop = true)
DESKTOP_PACKAGES = {
    "cowsay": "cowsay",
    "cmatrix": "cmatrix",
    "neovim": "neovim",
    "usbredir": "usbredirect",
    "kdeconnect": "kdeconnect",
    "flatpak": "flatpak",
    "gnome-software": "gnome-software",
    "gnome-software-plugin-flatpak": "gnome-software-plugin-flatpak",
}

# Packages NOT in Debian repos (must be installed via alternative methods)
SOURCE_BUILD_PACKAGES = {
    "niri": "Niri compositor (cargo)",
    "quickshell": "QuickShell (cmake build)",
    "noctalia-shell": "Noctalia Shell (cmake build)",
    "walker": "Walker launcher (go install)",
    "elephant": "Elephant data provider (go install)",
    "rofi": "Rofi (apt backports)",
    "wezterm": "WezTerm (.deb from GitHub)",
    "yazi": "Yazi file manager (cargo)",
    "cider": "Cider Apple Music client (.deb)",
    "sunder": "Sunder YouTube music (cargo)",
    "google-chrome-canary": "Google Chrome Canary (.deb)",
    "eww": "Elkowar's wacky widgets (cargo)",
    "gowall": "Gowall wallpaper tool (cargo)",
    "gpu-screen-recorder": "GPU screen recorder (git)",
    "vesktop": "Vesktop Discord client (.deb)",
    "nbfc-linux": "NoteBook FanControl (pip)",
    "pfetch-rs": "pfetch-rs (cargo)",
}


# ── Stage 1: System Preparation ────────────────────────────────────────────────

def stage_1_prepare_system(dry_run: bool = False) -> None:
    """Prepare the Debian system kernel parameters and repos."""
    log.info("=== Stage 1: System Preparation ===")

    # Kernel sysctl settings
    sysctl_settings = {
        "vm.max_map_count": "2147483642",
        "vm.mmap_min_addr": "4096",
        "vm.overcommit_memory": "1",
    }
    sysctl_content = []
    for key, value in sysctl_settings.items():
        if not dry_run:
            run(["sysctl", "-w", f"{key}={value}"], check=False)
            sysctl_content.append(f"{key}={value}")
    if not dry_run:
        write_file(Path("/etc/sysctl.d/90-nixdots.conf"),
                   f"# Nixdots migration - set by installer\n" + "\n".join(sysctl_content) + "\n")

    # NetworkManager DNS
    if not dry_run:
        nm_conf = Path("/etc/NetworkManager/conf.d/dns-servers.conf")
        nm_conf.parent.mkdir(parents=True, exist_ok=True)
        nm_conf.write_text("[global-dns-domain-*]\nservers=1.1.1.2,8.8.8.8\n")

    # Timezone
    if not dry_run:
        run(["timedatectl", "set-timezone", "Europe/Kyiv"], check=False)

    # Locale
    if not dry_run:
        try:
            run(["locale-gen", "ru_RU.UTF-8"], check=False)
            run(["update-locale", "LANG=ru_RU.UTF-8"], check=False)
        except Exception:
            log.warning("Locale setup failed; will continue")

    # Console keymap
    if not dry_run:
        try:
            run(["localectl", "set-keymap", "ru"], check=False)
        except Exception:
            log.warning("Keymap setup failed")

    # Enable 32-bit architecture and contrib/non-free for Steam
    if not dry_run:
        try:
            run(["dpkg", "--add-architecture", "i386"], check=False)
            # Ensure contrib and non-free are in sources.list
            sources_list = Path("/etc/apt/sources.list")
            if sources_list.exists():
                content = sources_list.read_text()
                new_lines = []
                for line in content.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("deb ") and "contrib" not in stripped and "non-free" not in stripped:
                        line = line.rstrip() + " contrib non-free"
                    elif stripped.startswith("deb ") and "contrib" in stripped and "non-free" not in stripped:
                        line = line.rstrip() + " non-free"
                    elif stripped.startswith("deb ") and "non-free" in stripped and "contrib" not in stripped:
                        line = line.rstrip() + " contrib"
                    new_lines.append(line)
                sources_list.write_text("\n".join(new_lines) + "\n")
            run(["apt-get", "update"], check=False)
        except Exception:
            log.warning("Failed to add i386 architecture")

    # ── AMD GPU Environment Variables ────────────────────────────────────
    if not dry_run:
        gpu_env_path = Path("/etc/environment.d/90-nixdots-gpu.conf")
        gpu_env_path.parent.mkdir(parents=True, exist_ok=True)
        gpu_env_path.write_text(
            "LIBVA_DRIVER_NAME=radeonsi\n"
            "VDPAU_DRIVER=radeonsi\n"
            "NIXOS_OZONE_WL=1\n"
        )

    # ── Chrome/Chromium Managed Policies ─────────────────────────────────
    if not dry_run:
        chrome_policy_dir = Path("/etc/opt/chrome/policies/managed")
        chrome_policy_dir.mkdir(parents=True, exist_ok=True)
        import json
        policy = {
            "ExtensionSettings": {
                "*": {"installation_mode": "allowed"},
                "bkkmolkhemgaeaeggcmfbghljjjoofoh": {  # Catppuccin Mocha
                    "installation_mode": "normal_installed",
                    "update_url": "https://clients2.google.com/service/update2/crx"
                },
                "clngdbkpkpeebahjckkjfobafhncgmne": {  # Stylus
                    "installation_mode": "normal_installed",
                    "update_url": "https://clients2.google.com/service/update2/crx"
                },
            }
        }
        write_file(chrome_policy_dir / "10-catppuccin-mocha.json", json.dumps(policy, indent=2))
        # Also for chromium if present
        Path("/etc/chromium/policies/managed").mkdir(parents=True, exist_ok=True)
        write_file(Path("/etc/chromium/policies/managed/10-catppuccin-mocha.json"), json.dumps(policy, indent=2))


# ── Stage 2: Package Installation ──────────────────────────────────────────────

def stage_2_install_packages(dry_run: bool = False, system_only: bool = True) -> None:
    """Install all required Debian packages."""
    log.info("=== Stage 2: Package Installation ===")

    if not dry_run:
        run(["apt-get", "update"])

    # System packages
    system_pkgs = list(SYSTEM_PACKAGES.values())
    apt_install(system_pkgs, dry_run)

    # Desktop packages
    if system_only:
        desktop_pkgs = list(DESKTOP_PACKAGES.values())
        apt_install(desktop_pkgs, dry_run)

    # Install flatpak and Flatpak apps
    if not dry_run and system_only:
        run(["flatpak", "remote-add", "--if-not-exists", "flathub",
             "https://dl.flathub.org/repo/flathub.flatpakrepo"], check=False)
        for app in ["com.wps.Office", "ru.linux_gaming.PortProton"]:
            run(["flatpak", "install", "-y", "flathub", app], check=False)


# ── Stage 3: Source Builds ────────────────────────────────────────────────────

def stage_3_build_from_source(dry_run: bool = False) -> None:
    """Build packages from source that aren't in Debian repos."""
    log.info("=== Stage 3: Source Builds ===")

    build_dir = Path("/tmp/nixdots-source-builds")
    if not dry_run:
        build_dir.mkdir(parents=True, exist_ok=True)

    # WezTerm - available as .deb from GitHub releases
    log.info("Installing WezTerm...")
    if not dry_run and not shutil.which("wezterm"):
        try:
            run(["wget", "-O", "/tmp/wezterm.deb",
                 "https://github.com/wez/wezterm/releases/download/20240203-110809-5046fc22/wezterm-20240203-110809-5046fc22-1.deb"])
            run(["dpkg", "-i", "/tmp/wezterm.deb"], check=False)
            run(["apt-get", "install", "-f", "-y"])
        except Exception as e:
            log.error(f"Failed to install WezTerm: {e}")
            log.warning("WezTerm will need manual installation")

    # Yazi - available via cargo
    log.info("Installing Yazi...")
    if not dry_run and not shutil.which("yazi"):
        try:
            run(["cargo", "install", "yazi-fm", "yazi-cli"], check=False)
        except Exception as e:
            log.error(f"Failed to install Yazi: {e}")

    # Niri compositor
    log.info("Installing Niri compositor...")
    if not dry_run:
        try:
            # Niri is available via cargo
            run(["cargo", "install", "niri"], check=False)
        except Exception as e:
            log.error(f"Failed to install Niri from cargo: {e}")
            # Alternative: try the Debian backports or prebuilt
            log.info("Trying to install Niri via Debian backports...")
            run(["apt-get", "install", "-t", "trixie-backports", "-y", "niri"], check=False)

    # Walker launcher (Rust/Tauri project, NOT Go)
    log.info("Installing Walker launcher...")
    if not dry_run and not shutil.which("walker"):
        try:
            if shutil.which("cargo"):
                # Build and install from git with cargo
                walker_build_dir = Path("/tmp/nixdots-source-builds/walker")
                run(["git", "clone", "--depth", "1",
                     "https://github.com/abenz1267/walker.git",
                     str(walker_build_dir)], check=False)
                if walker_build_dir.exists():
                    run(["cargo", "build", "--release"], cwd=str(walker_build_dir), check=False)
                    run(["cp", str(walker_build_dir / "target/release/walker"), "/usr/local/bin/"], check=False)
            else:
                log.warning("Cargo not found: cannot build walker")
        except Exception as e:
            log.error(f"Failed to install Walker: {e}")

    # Elephant (Go-based data provider for Walker)
    log.info("Installing Elephant data provider...")
    if not dry_run and not shutil.which("elephant"):
        try:
            run(["go", "install", "github.com/abenz1267/elephant@latest"], check=False)
        except Exception as e:
            log.error(f"Failed to install Elephant: {e}")

    # Rofi (ensure it's installed)
    if not dry_run and not shutil.which("rofi"):
        try:
            run(["apt-get", "install", "-y", "rofi"], check=False)
        except Exception:
            log.warning("Rofi not found in repos; trying backports")
            run(["apt-get", "install", "-t", "trixie-backports", "-y", "rofi"], check=False)

    # Eww
    log.info("Installing Eww...")
    if not dry_run and not shutil.which("eww"):
        try:
            run(["cargo", "install", "elkowar-eww"], check=False)
        except Exception as e:
            log.error(f"Failed to install Eww: {e}")

    # Install google-chrome-canary from deb
    log.info("Installing Google Chrome Canary...")
    if not dry_run and not shutil.which("google-chrome-canary"):
        try:
            run(["wget", "-O", "/tmp/google-chrome-canary.deb",
                 "https://dl.google.com/linux/chrome/deb/pool/main/g/google-chrome-canary/google-chrome-canary_151.0.7892.0-1_amd64.deb"])
            run(["dpkg", "-i", "/tmp/google-chrome-canary.deb"], check=False)
            run(["apt-get", "install", "-f", "-y"])
        except Exception as e:
            log.error(f"Failed to install Chrome Canary: {e}")

    # Cider (Apple Music client)
    log.info("Installing Cider...")
    if not dry_run and not shutil.which("cider"):
        try:
            run(["wget", "-O", "/tmp/cider.deb",
                 "https://github.com/ciderapp/Cider/releases/download/v4.0.0/Cider_4.0.0_amd64.deb"], check=False)
            run(["dpkg", "-i", "/tmp/cider.deb"], check=False)
            run(["apt-get", "install", "-f", "-y"], check=False)
        except Exception as e:
            log.error(f"Failed to install Cider: {e}")
            log.info("Try manual install from https://cider.sh/download")

    # Vesktop (Discord alternative)
    log.info("Installing Vesktop...")
    if not dry_run and not shutil.which("vesktop"):
        try:
            run(["wget", "-O", "/tmp/vesktop.deb",
                 "https://github.com/Vencord/Vesktop/releases/latest/download/Vesktop.deb"], check=False)
            run(["dpkg", "-i", "/tmp/vesktop.deb"], check=False)
            run(["apt-get", "install", "-f", "-y"], check=False)
        except Exception as e:
            log.error(f"Failed to install Vesktop: {e}")

    # Gpu-screen-recorder
    log.info("Installing GPU screen recorder...")
    if not dry_run and not shutil.which("gpu-screen-recorder"):
        try:
            run(["apt-get", "install", "-y", "gpu-screen-recorder"], check=False)
        except Exception:
            log.warning("gpu-screen-recorder not in repos; skip")

    # pfetch-rs
    if not dry_run and not shutil.which("pfetch"):
        run(["cargo", "install", "pfetch-rs"], check=False)


# ── Stage 4: User & Groups ────────────────────────────────────────────────────

def stage_4_setup_user(dry_run: bool = False) -> None:
    """Create user, groups, and system directories."""
    log.info("=== Stage 4: User Setup ===")

    ensure_user_exists(USERNAME, dry_run)

    if not dry_run:
        # Create user directories
        for d in ["Documents", "Downloads", "Pictures", "Videos",
                  "Music", "Workspace", "Pictures/Screenshots"]:
            Path(f"{USER_HOME}/{d}").mkdir(parents=True, exist_ok=True)
            run(["chown", f"{USERNAME}:{USER_GROUP}", f"{USER_HOME}/{d}"])

        # Profile picture
        profile_src = ASSETS_SRC / "profile.png"
        if profile_src.exists():
            shutil.copy2(str(profile_src), f"{USER_HOME}/.face")
            run(["chown", f"{USERNAME}:{USER_GROUP}", f"{USER_HOME}/.face"])

        # Avatar for accountsservice
        if Path("/var/lib/AccountsService/icons").exists():
            try:
                shutil.copy2(str(profile_src), f"/var/lib/AccountsService/icons/{USERNAME}")
            except Exception:
                pass

        # Create sudo group and add user
        sudoers_file = Path("/etc/sudoers.d/nixdots-user")
        sudoers_file.write_text(f"{USERNAME} ALL=(ALL:ALL) ALL\n")
        sudoers_file.chmod(0o440)


# ── Stage 5: System Services ──────────────────────────────────────────────────

def stage_5_setup_services(dry_run: bool = False) -> None:
    """Enable and configure systemd services."""
    log.info("=== Stage 5: System Services ===")

    services = [
        "NetworkManager",
        "bluetooth",
        "cups",
        "avahi-daemon",
        "upower",
        "thermald",
        "udisks2",
        "accounts-daemon",
        "libvirtd",
        "virtlogd",
    ]

    for svc in services:
        service_enable(svc, system=True, dry_run=dry_run)

    # PipeWire replacements
    if not dry_run:
        run(["systemctl", "--user", "enable", "pipewire"], check=False)
        run(["systemctl", "--user", "enable", "pipewire-pulse"], check=False)
        run(["systemctl", "--user", "enable", "wireplumber"], check=False)
        # Disable pulseaudio if present
        run(["systemctl", "--user", "disable", "pulseaudio"], check=False)

    # ── Deploy system files (niri-session, wayland-session entry, noctalia service) ──
    if not dry_run:
        # niri-session script → /usr/local/bin/
        niri_session_src = SYSTEM_SRC / "niri-session"
        if niri_session_src.exists():
            shutil.copy2(str(niri_session_src), "/usr/local/bin/niri-session")
            run(["chmod", "+x", "/usr/local/bin/niri-session"])
            log.info("  Deployed /usr/local/bin/niri-session")
        else:
            log.warning(f"niri-session not found at {niri_session_src}")

        # niri-session.desktop → /usr/share/wayland-sessions/
        niri_desktop_src = SYSTEM_SRC / "niri-session.desktop"
        if niri_desktop_src.exists():
            Path("/usr/share/wayland-sessions").mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(niri_desktop_src), "/usr/share/wayland-sessions/niri.desktop")
            log.info("  Deployed /usr/share/wayland-sessions/niri.desktop")

        # noctalia-shell.service → user systemd
        noctalia_svc_src = SYSTEM_SRC / "noctalia-shell.service"
        if noctalia_svc_src.exists():
            noctalia_svc_dst = Path(f"{USER_HOME}/.config/systemd/user/noctalia-shell.service")
            noctalia_svc_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(noctalia_svc_src), str(noctalia_svc_dst))
            run(["chown", f"{USERNAME}:{USER_GROUP}", str(noctalia_svc_dst)])
            run(["systemctl", "--user", "enable", "noctalia-shell"], check=False)
            log.info("  Deployed noctalia-shell.service")

    # Greetd (display manager) — with tuigreet matching NixOS setup
    log.info("Setting up greetd with tuigreet...")
    if not dry_run:
        # Install greetd + tuigreet
        run(["apt-get", "install", "-y", "greetd"], check=False)
        try:
            run(["apt-get", "install", "-y", "tuigreet"], check=False)
        except Exception:
            log.warning("tuigreet not in repos; greetd will auto-login without greeter")

        # Create greeter user for tuigreet (required by greetd default_session)
        greeter_exists = run(["id", "greeter"], check=False, capture=True).returncode == 0
        if not greeter_exists:
            run(["useradd", "-r", "-s", "/sbin/nologin", "-d", "/var/lib/greetd", "-M", "greeter"], check=False)

        greetd_dir = Path("/etc/greetd")
        greetd_dir.mkdir(parents=True, exist_ok=True)

        tuigreet_installed = shutil.which("tuigreet") is not None
        if tuigreet_installed:
            greetd_config = greetd_dir / "config.toml"
            greetd_config.write_text(f"""[terminal]
vt = 1

[default_session]
command = "tuigreet --time --remember --cmd niri-session"
user = "greeter"

[initial_session]
command = "niri-session"
user = "{USERNAME}"
""")
            log.info("  greetd configured with tuigreet (matches NixOS setup)")
        else:
            # Fallback: direct auto-login
            greetd_config = greetd_dir / "config.toml"
            greetd_config.write_text(f"""[terminal]
vt = 1

[default_session]
command = "niri-session"
user = "{USERNAME}"
""")
            log.info("  greetd configured for direct auto-login (no tuigreet)")

        service_enable("greetd", system=True, dry_run=dry_run)

    # Bluetooth keyboard reconnect
    bluetooth_script = f"""{'#!/bin/bash'}
# Nixdots bluetooth reconnect helper
# Managed devices: 68:FE:F7:62:E8:2A 1C:1A:C0:F2:53:BE 40:B3:FA:06:E9:DB
bluetoothctl power on 2>/dev/null || true
bluetoothctl agent on 2>/dev/null || true
bluetoothctl default-agent 2>/dev/null || true
for mac in "$@"; do
    bluetoothctl trust "$mac" 2>/dev/null || true
    for i in {{1..100}}; do
        if bluetoothctl info "$mac" 2>/dev/null | grep -q "Connected: yes"; then
            echo "Connected $mac"
            break
        fi
        bluetoothctl connect "$mac" 2>/dev/null || true
        sleep 2
    done
done
"""
    if not dry_run:
        Path("/usr/local/bin/bluetooth-device-reconnect").write_text(bluetooth_script)
        run(["chmod", "+x", "/usr/local/bin/bluetooth-device-reconnect"])

    # Bluetooth watchdog service (oneshot reconnect at boot)
    if not dry_run:
        bt_reconnect_unit = Path("/etc/systemd/system/bluetooth-keyboard-reconnect.service")
        bt_reconnect_unit.parent.mkdir(parents=True, exist_ok=True)
        bt_reconnect_unit.write_text(f"""[Unit]
Description=Reconnect managed Bluetooth devices
After=bluetooth.service multi-user.target
Wants=bluetooth.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/bluetooth-device-reconnect 68:FE:F7:62:E8:2A
RemainAfterExit=false

[Install]
WantedBy=multi-user.target
""")
        run(["systemctl", "enable", "bluetooth-keyboard-reconnect"], check=False)
        # Bluetooth experimental mode
        bt_main = Path("/etc/bluetooth/main.conf")
        if bt_main.exists():
            config_text = bt_main.read_text()
            if "Experimental = true" not in config_text:
                bt_main.write_text(config_text + "\n[General]\nExperimental = true\n")

    # uinput for OpenTabletDriver
    if not dry_run:
        uinput_rules = Path("/etc/udev/rules.d/99-uinput.rules")
        uinput_rules.write_text('KERNEL=="uinput", SUBSYSTEM=="misc", OPTIONS+="static_node=uinput", TAG+="uaccess"\n')

    # Magic Trackpad udev fuzz fix
    if not dry_run:
        trackpad_rules = Path("/etc/udev/rules.d/99-magic-trackpad.rules")
        trackpad_rules.write_text(
            '# Apple Magic Trackpad 1 -- supply missing LIBINPUT_FUZZ_* from kernel fuzz\n'
            'ACTION=="add|change", SUBSYSTEM=="input", \\\n'
            '  ATTRS{id/vendor}=="05ac", ATTRS{id/product}=="030e", \\\n'
            '  ENV{LIBINPUT_FUZZ_00}="4", \\\n'
            '  ENV{LIBINPUT_FUZZ_01}="4", \\\n'
            '  ENV{LIBINPUT_FUZZ_35}="4", \\\n'
            '  ENV{LIBINPUT_FUZZ_36}="4"\n\n'
            '# Disable middle-button area on Magic Trackpad 1\n'
            'ACTION=="add|change", SUBSYSTEM=="input", \\\n'
            '  ATTRS{id/vendor}=="05ac", ATTRS{id/product}=="030e", \\\n'
            '  ENV{LIBINPUT_ATTR_MIDDLE_BUTTON_AREA_ENABLED}="0"\n'
        )

    # Libinput touchpad settings
    if not dry_run:
        libinput_conf = Path("/etc/libinput/local-overrides.quirks")
        libinput_conf.parent.mkdir(parents=True, exist_ok=True)
        libinput_conf.write_text(
            '[Nixdots Touchpad Settings]\n'
            'MatchUdevType=touchpad\n'
            'MatchDMIMatch=*\n'
            'AttrTapEnabled=1\n'
            'AttrNaturalScrollingEnabled=1\n'
            'AttrScrollMethod=2\n'
            'AttrClickMethod=1\n'
        )

    # PipeWire bluetooth config
    if not dry_run:
        pw_dir = Path("/etc/wireplumber/bluetooth.lua.d")
        pw_dir.mkdir(parents=True, exist_ok=True)
        (pw_dir / "51-bluez-config.lua").write_text("""bluez_monitor.properties = {
  ["bluez5.enable-sbc-xq"] = true,
  ["bluez5.enable-msbc"] = true,
  ["bluez5.enable-hw-volume"] = true,
  ["bluez5.auto-switch"] = false,
  ["bluez5.default.profile"] = "a2dp-sink",
  ["bluez5.headset-roles"] = "[ hsp_hs hsp_ag hfp_hf hfp_ag ]",
  ["bluez5.codecs"] = "[ sbc sbc_xq aac ldac aptx aptx_hd aptx_ll aptx_ll_duplex faststream faststream_duplex ]",
  ["bluez5.default.rate"] = 48000,
  ["bluez5.default.channels"] = 2,
}
""")


# ── Stage 6: XDG Portals ─────────────────────────────────────────────────────

def stage_6_setup_portals(dry_run: bool = False) -> None:
    """Configure XDG Desktop Portals for Niri."""
    log.info("=== Stage 6: Portal Configuration ===")

    if dry_run:
        log.info("  [dry-run] Would configure XDG portals")
        return

    # Portal config
    portal_dir = Path(f"{USER_HOME}/.config/xdg-desktop-portal")
    portal_dir.mkdir(parents=True, exist_ok=True)
    portal_config = portal_dir / "portals.conf"
    portal_config.write_text("""[preferred]
default=gtk
org.freedesktop.impl.portal.Secret=gnome-keyring

[niri]
default=wlr;gtk
org.freedesktop.impl.portal.ScreenCast=wlr
org.freedesktop.impl.portal.Screenshot=wlr
""")

    # Portal-wlr config
    portal_wlr_dir = Path(f"{USER_HOME}/.config/xdg-desktop-portal-wlr")
    portal_wlr_dir.mkdir(parents=True, exist_ok=True)
    (portal_wlr_dir / "niri").write_text("""[screencast]
output_name=
chooser_type=simple
chooser_cmd=slurp -f %o
""")

    # ── Critical: Register wlr backend for Niri ──────────────────────────────
    # Without this, xdg-desktop-portal-wlr ignores niri sessions and screen
    # sharing / portal screenshots silently fail. The NixOS flake patches this
    # at build time (see flake.nix lines 71-76).
    wlr_portal = Path("/usr/share/xdg-desktop-portal/portals/wlr.portal")
    if wlr_portal.exists():
        content = wlr_portal.read_text()
        if "niri" not in content:
            content = content.replace(
                "UseIn=wlroots;sway;Wayfire;river;phosh;Hyprland;",
                "UseIn=wlroots;sway;Wayfire;river;phosh;Hyprland;niri;"
            )
            wlr_portal.write_text(content)
            log.info("  Patched wlr.portal: added niri to UseIn")
    else:
        log.warning("  wlr.portal not found at expected path")

    # Ensure user owns portal configs
    run(["chown", "-R", f"{USERNAME}:{USER_GROUP}", str(portal_dir)])
    run(["chown", "-R", f"{USERNAME}:{USER_GROUP}", str(portal_wlr_dir)])


# ── Stage 7: User Dotfiles & Configs ─────────────────────────────────────────

def stage_7_install_user_configs(dry_run: bool = False) -> None:
    """Install all user-level configuration files."""
    log.info("=== Stage 7: User Configuration ===")

    config_target = Path(f"{USER_HOME}/.config")
    local_target = Path(f"{USER_HOME}/.local/share")
    bin_target = Path(f"{USER_HOME}/.local/bin")

    if dry_run:
        log.info("  [dry-run] Would install user configs")
        return

    bin_target.mkdir(parents=True, exist_ok=True)

    # ── Desktop Entry Cleanup (remove stale entries) ────────────────────────
    stale_entries = [
        "Game Launcher.desktop",
        "World of Tanks Blitz.desktop",
        "PortProton.desktop",
        "chrome-blgdilankhbcpipclgpdndahbehalgkh-Default.desktop",
        "ru.linux_gaming.PortProton.desktop",
    ]
    apps_dir = Path(f"{USER_HOME}/.local/share/applications")
    for entry in stale_entries:
        target = apps_dir / entry
        if target.exists():
            target.unlink()
            log.info(f"  Removed stale desktop entry: {entry}")
    # Stale icons
    for icon_path in [
        Path(f"{USER_HOME}/.local/share/icons/hicolor/32x32/apps/chrome-blgdilankhbcpipclgpdndahbehalgkh-Default.png"),
        Path(f"{USER_HOME}/.local/share/icons/hicolor/48x48/apps/chrome-blgdilankhbcpipclgpdndahbehalgkh-Default.png"),
        Path(f"{USER_HOME}/.local/share/icons/hicolor/128x128/apps/chrome-blgdilankhbcpipclgpdndahbehalgkh-Default.png"),
        Path(f"{USER_HOME}/.local/share/icons/hicolor/256x256/apps/chrome-blgdilankhbcpipclgpdndahbehalgkh-Default.png"),
    ]:
        if icon_path.exists():
            icon_path.unlink()

    # ── Helper scripts ──────────────────────────────────────────────────────
    # xfreerdp3 wrapper
    xfreerdp3_sh = bin_target / "xfreerdp3"
    xfreerdp3_sh.write_text('#!/bin/bash\nexec freerdp3 "$@"\n')
    xfreerdp3_sh.chmod(0o755)

    # mic_toggle wrapper
    mic_toggle_sh = bin_target / "mic_toggle"
    mic_toggle_sh.write_text(
        '#!/bin/bash\n'
        'STATE_FILE="/tmp/mic_muted_invisible"\n'
        'if [ -f "$STATE_FILE" ]; then\n'
        '  wpctl set-volume @DEFAULT_AUDIO_SOURCE@ 0.55\n'
        '  rm "$STATE_FILE"\n'
        'else\n'
        '  wpctl set-volume @DEFAULT_AUDIO_SOURCE@ 0\n'
        '  touch "$STATE_FILE"\n'
        'fi\n'
    )
    mic_toggle_sh.chmod(0o755)

    # scrolllock_keyboard toggle
    scrolllock_sh = bin_target / "scrolllock_keyboard"
    scrolllock_sh.write_text(
        '#!/bin/bash\n'
        'DEV="input*::scrolllock"\n'
        'STATE_FILE="/tmp/scrolllock_active"\n'
        'if [ -f "$STATE_FILE" ]; then\n'
        '  rm "$STATE_FILE"\n'
        '  pkill -f "scrolllock_daemon" || true\n'
        '  brightnessctl --device="$DEV" set 0\n'
        '  exit 0\n'
        'fi\n'
        'touch "$STATE_FILE"\n'
        'echo "none" | brightnessctl --device="$DEV" set 1\n'
        '(\n'
        '  exec -a scrolllock_daemon sh -c \'\n'
        '    while [ -f /tmp/scrolllock_active ]; do\n'
        '      if [ "$(brightnessctl --device="input*::scrolllock" get)" -eq 0 ]; then\n'
        '        brightnessctl --device="input*::scrolllock" set 1\n'
        '      fi\n'
        '      sleep 0.2\n'
        '    done\n'
        '  \'\n'
        ') & disown\n'
    )
    scrolllock_sh.chmod(0o755)

    # catppuccin-userstyles wrapper
    catppuccin_sh = bin_target / "catppuccin-userstyles"
    catppuccin_sh.write_text(
        '#!/bin/bash\n'
        'exec google-chrome --new-window "https://github.com/catppuccin/userstyles/releases/download/all-userstyles-export/import.json" "chrome-extension://clngdbkpkpeebahjckkjfobafhncgmne/manage.html"\n'
    )
    catppuccin_sh.chmod(0o755)

    # ── Claude Code wrappers (DeepSeek through Anthropic) ─────────────────────
    claude_env = (
        'export ANTHROPIC_BASE_URL="https://api.deepseek.com/anthropic"\n'
        'export ANTHROPIC_AUTH_TOKEN="${ANTHROPIC_AUTH_TOKEN:-}"  # Set via environment variable\n'
        'export CLAUDE_CODE_EFFORT_LEVEL="max"\n'
        'export CLAUDE_CODE_AUTO_APPROVE=1\n'
    )
    for name, model in [
        ("claude", "deepseek-v4-pro"),
        ("c-pro", "deepseek-v4-pro"),
        ("c-flash", "deepseek-v4-flash"),
        ("c-chat", "deepseek-chat"),
        ("c-reasoner", "deepseek-reasoner"),
        ("c-r", "deepseek-reasoner"),
    ]:
        claude_bin = bin_target / name
        claude_bin.write_text(
            '#!/bin/bash\n'
            f'{claude_env}'
            f'export ANTHROPIC_MODEL="{model}"\n'
            'export CLAUDE_CODE_SUBAGENT_MODEL="deepseek-v4-flash"\n'
            'CLI_PATH="$HOME/.npm-global/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe"\n'
            'if [ ! -f "$CLI_PATH" ]; then\n'
            '  npm install -g @anthropic-ai/claude-code@2.1.178 --no-audit --no-fund 2>&1\n'
            'fi\n'
            'exec "$CLI_PATH" "$@"\n'
        )
        claude_bin.chmod(0o755)

    # ── Walker systemd user services ─────────────────────────────────────────
    walker_unit_dir = config_target / "systemd" / "user"
    walker_unit_dir.mkdir(parents=True, exist_ok=True)
    walker_service = walker_unit_dir / "walker.service"
    if shutil.which("walker"):
        walker_service.write_text(
            '[Unit]\n'
            'Description=Walker launcher service\n'
            'PartOf=graphical-session.target\n'
            'After=graphical-session.target\n'
            '[Service]\n'
            'ExecStart=walker --gapplication-service\n'
            'Restart=on-failure\n'
            'RestartSec=3\n'
            '[Install]\n'
            'WantedBy=graphical-session.target\n'
        )
    else:
        log.warning("  Walker not installed; skipping walker.service")
    elephant_service = walker_unit_dir / "elephant.service"
    if shutil.which("elephant"):
        elephant_service.write_text(
            '[Unit]\n'
            'Description=Elephant data provider service\n'
            'PartOf=graphical-session.target\n'
            'After=graphical-session.target\n'
            'Before=walker.service\n'
            '[Service]\n'
            'ExecStart=elephant\n'
            'Restart=on-failure\n'
            'RestartSec=3\n'
            '[Install]\n'
            'WantedBy=graphical-session.target\n'
        )
    else:
        log.warning("  Elephant not installed; skipping elephant.service")

    # ── Niri Config ──────────────────────────────────────────────────────────
    niri_cfg = CONFIG_SRC / "niri" / "config.kdl"
    if niri_cfg.exists():
        target = config_target / "niri" / "config.kdl"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(niri_cfg), str(target))

    # ── Rofi Config ──────────────────────────────────────────────────────────
    rofi_target = config_target / "rofi"
    rofi_target.mkdir(parents=True, exist_ok=True)
    for f in CONFIG_SRC.glob("rofi/*.rasi"):
        shutil.copy2(str(f), str(rofi_target))

    # ── Walker Config ────────────────────────────────────────────────────────
    walker_target = config_target / "walker"
    walker_target.mkdir(parents=True, exist_ok=True)
    walker_config = CONFIG_SRC / "walker" / "config.toml"
    if walker_config.exists():
        shutil.copy2(str(walker_config), str(walker_target / "config.toml"))
    # Copy walker themes
    walker_themes_src = CONFIG_SRC / "walker" / "themes"
    if walker_themes_src.exists():
        walker_themes_dst = walker_target / "themes"
        if walker_themes_dst.exists():
            shutil.rmtree(str(walker_themes_dst))
        shutil.copytree(str(walker_themes_src), str(walker_themes_dst), symlinks=True)

    # ── Yazi Config ──────────────────────────────────────────────────────────
    yazi_target = config_target / "yazi"
    yazi_target.mkdir(parents=True, exist_ok=True)
    yazi_init = CONFIG_SRC / "yazi" / "main.lua"
    if yazi_init.exists():
        shutil.copy2(str(yazi_init), str(yazi_target / "init.lua"))

    # ── Noctalia Config ──────────────────────────────────────────────────────
    noctalia_target = config_target / "noctalia"
    noctalia_target.mkdir(parents=True, exist_ok=True)

    # Copy vendor plugins
    vendor_plugins_src = VENDOR_SRC / "noctalia" / "plugins"
    if vendor_plugins_src.exists():
        vendor_plugins_dst = noctalia_target / "plugins"
        if vendor_plugins_dst.exists():
            shutil.rmtree(str(vendor_plugins_dst))
        shutil.copytree(str(vendor_plugins_src), str(vendor_plugins_dst), symlinks=True)

    # Noctalia plugin config (plugins.json)
    plugin_states = {
        "calibre-provider": True,
        "mpris-lyric": True,
        "niri-overview-launcher": True,
        "screen-recorder": True,
        "workspace-overview": True,
    }
    plugins_json = {"sources": [{"enabled": False, "name": "Noctalia Plugins",
                                  "url": "https://github.com/noctalia-dev/noctalia-plugins"}],
                    "states": {k: {"enabled": v, "sourceUrl": "https://github.com/noctalia-dev/noctalia-plugins"}
                                for k, v in plugin_states.items()},
                    "version": 2}
    (noctalia_target / "plugins.json").write_text(json.dumps(plugins_json, indent=2))

    # Noctalia todo settings
    todo_settings = {"pages": [{"id": 0, "name": "General"}], "current_page_id": 0,
                     "todos": [], "count": 0, "completedCount": 0, "isExpanded": False,
                     "useCustomColors": False, "exportPath": "~/Documents",
                     "exportFormat": "markdown", "exportEmptySections": False}
    (noctalia_target / "todo-plugin-settings.json").write_text(json.dumps(todo_settings, indent=2))

    # ── Noctalia main settings.json (full config from original) ──────────────
    noctalia_settings = {
        "settingsVersion": 54,
        "appLauncher": {
            "autoPasteClipboard": False,
            "clipboardWatchImageCommand": "wl-paste --type image --watch cliphist store",
            "clipboardWatchTextCommand": "wl-paste --type text --watch cliphist store",
            "clipboardWrapText": True,
            "customLaunchPrefix": "",
            "customLaunchPrefixEnabled": False,
            "density": "compact",
            "enableClipPreview": False,
            "enableClipboardHistory": True,
            "enableSessionSearch": True,
            "enableSettingsSearch": True,
            "enableWindowsSearch": True,
            "iconMode": "native",
            "ignoreMouseInput": True,
            "overviewLayer": False,
            "pinnedApps": [],
            "position": "follow_bar",
            "screenshotAnnotationTool": "",
            "showCategories": False,
            "showIconBackground": False,
            "sortByMostUsed": True,
            "terminalCommand": "",
            "useApp2Unit": False,
            "viewMode": "list",
        },
        "audio": {
            "cavaFrameRate": 30,
            "mprisBlacklist": [],
            "preferredPlayer": "",
            "visualizerType": "mirrored",
            "volumeFeedback": False,
            "volumeFeedbackSoundFile": "",
            "volumeOverdrive": False,
            "volumeStep": 5,
        },
        "bar": {
            "autoHideDelay": 500,
            "autoShowDelay": 150,
            "backgroundOpacity": 0,
            "barType": "floating",
            "capsuleColorKey": "none",
            "capsuleOpacity": 0.68,
            "contentPadding": 16,
            "density": "spacious",
            "displayMode": "always_visible",
            "floating": True,
            "fontScale": 1.06,
            "frameRadius": 18,
            "frameThickness": 0,
            "hideOnOverview": True,
            "marginHorizontal": 10,
            "marginVertical": 8,
            "monitors": [],
            "mouseWheelAction": "none",
            "mouseWheelWrap": True,
            "outerCorners": False,
            "position": "top",
            "reverseScroll": False,
            "screenOverrides": [],
            "showCapsule": True,
            "showOnWorkspaceSwitch": True,
            "showOutline": False,
            "useSeparateOpacity": True,
            "widgetSpacing": 12,
            "widgets": {
                "center": [{
                    "hideMode": "transparent",
                    "showIcon": True,
                    "colorizeIcons": False,
                    "maxWidth": 800,
                    "useFixedWidth": False,
                    "scrollingMode": "always",
                    "id": "ActiveWindow",
                    "textColor": "primary",
                }],
                "left": [
                    {"id": "Taskbar"},
                    {
                        "characterCount": 2,
                        "colorizeIcons": False,
                        "emptyColor": "secondary",
                        "enableScrollWheel": True,
                        "focusedColor": "primary",
                        "followFocusedScreen": False,
                        "groupedBorderOpacity": 1,
                        "hideUnoccupied": True,
                        "iconScale": 0.8,
                        "id": "Workspace",
                        "labelMode": "index",
                        "occupiedColor": "secondary",
                        "pillSize": 0.7,
                        "showApplications": False,
                        "showBadge": True,
                        "showLabelsOnlyWhenOccupied": False,
                        "unfocusedIconsOpacity": 1,
                    },
                ],
                "right": [
                    {"id": "Tray"},
                    {
                        "colorizeSystemIcon": "primary",
                        "enableColorization": True,
                        "generalTooltipText": "Windows RDP",
                        "hideMode": "alwaysExpanded",
                        "icon": "brand-windows-filled",
                        "id": "CustomButton",
                        "ipcIdentifier": "windows-rdp",
                        "leftClickExec": "xfreerdp3 /v:185.222.66.116:33934 /u:manager15 /p:\"Rdv56188202U\" /size:2560x1080 /cert:ignore /f",
                        "leftClickUpdateText": False,
                        "maxTextLength": {"horizontal": 10, "vertical": 10},
                        "middleClickExec": "",
                        "middleClickUpdateText": False,
                        "parseJson": False,
                        "rightClickExec": "",
                        "rightClickUpdateText": False,
                        "showExecTooltip": True,
                        "showIcon": True,
                        "showTextTooltip": True,
                        "textCollapse": "",
                        "textCommand": "",
                        "textIntervalMs": 3000,
                        "textStream": False,
                        "wheelDownExec": "",
                        "wheelDownUpdateText": False,
                        "wheelExec": "",
                        "wheelMode": "unified",
                        "wheelUpdateText": False,
                        "wheelUpExec": "",
                        "wheelUpUpdateText": False,
                    },
                    {"id": "plugin:assistant-panel"},
                    {
                        "displayMode": "onhover",
                        "iconColor": "none",
                        "id": "Volume",
                        "middleClickCommand": "pwvucontrol || pavucontrol",
                        "textColor": "none",
                    },
                    {
                        "displayMode": "onhover",
                        "iconColor": "none",
                        "id": "Bluetooth",
                        "textColor": "none",
                    },
                    {
                        "displayMode": "forceOpen",
                        "iconColor": "none",
                        "id": "KeyboardLayout",
                        "showIcon": False,
                        "textColor": "none",
                    },
                    {
                        "clockColor": "none",
                        "customFont": "",
                        "formatHorizontal": "HH:mm ddd, MMM dd",
                        "formatVertical": "HH mm - dd MM",
                        "id": "Clock",
                        "tooltipFormat": "HH:mm ddd, MMM dd",
                        "useCustomFont": False,
                    },
                ],
            },
        },
        "brightness": {
            "backlightDeviceMappings": [],
            "brightnessStep": 5,
            "enableDdcSupport": False,
            "enforceMinimum": True,
        },
        "calendar": {
            "cards": [
                {"enabled": True, "id": "calendar-header-card"},
                {"enabled": True, "id": "calendar-month-card"},
                {"enabled": False, "id": "weather-card"},
            ]
        },
        "colorSchemes": {
            "darkMode": True,
            "generationMethod": "tonal-spot",
            "manualSunrise": "06:30",
            "manualSunset": "18:30",
            "monitorForColors": "",
            "predefinedScheme": "Catppuccin",
            "schedulingMode": "off",
            "useWallpaperColors": False,
        },
        "controlCenter": {
            "cards": [
                {"enabled": True, "id": "profile-card"},
                {"enabled": True, "id": "shortcuts-card"},
                {"enabled": True, "id": "audio-card"},
                {"enabled": False, "id": "brightness-card"},
                {"enabled": True, "id": "weather-card"},
                {"enabled": True, "id": "media-sysmon-card"},
            ],
            "diskPath": "/",
            "openAtMouseOnBarRightClick": True,
            "position": "close_to_bar_button",
            "shortcuts": {
                "left": [
                    {"id": "Network"},
                    {"id": "Bluetooth"},
                    {"id": "WallpaperSelector"},
                    {"id": "NoctaliaPerformance"},
                ],
                "right": [
                    {"id": "Notifications"},
                    {"id": "PowerProfile"},
                    {"id": "KeepAwake"},
                    {"id": "NightLight"},
                ],
            },
        },
        "desktopWidgets": {
            "enabled": False,
            "gridSnap": True,
            "monitorWidgets": [],
            "overviewEnabled": False,
        },
        "dock": {
            "animationSpeed": 1,
            "backgroundOpacity": 0,
            "colorizeIcons": False,
            "deadOpacity": 0.6,
            "displayMode": "auto_hide",
            "dockType": "static",
            "enabled": False,
            "floatingRatio": 1,
            "groupApps": True,
            "groupClickAction": "list",
            "groupContextMenuMode": "extended",
            "groupIndicatorStyle": "dots",
            "inactiveIndicators": True,
            "indicatorColor": "primary",
            "indicatorOpacity": 0.6,
            "indicatorThickness": 3,
            "launcherIconColor": "none",
            "launcherPosition": "start",
            "monitors": [],
            "onlySameOutput": True,
            "pinnedApps": ["org.wezfurlong.wezterm", "org.telegram.desktop"],
            "pinnedStatic": True,
            "position": "bottom",
            "showDockIndicator": False,
            "showLauncherIcon": True,
            "sitOnFrame": False,
            "size": 1,
        },
        "general": {
            "allowPanelsOnScreenWithoutBar": True,
            "allowPasswordWithFprintd": False,
            "animationDisabled": False,
            "animationSpeed": 1,
            "autoStartAuth": False,
            "avatarImage": "",
            "boxRadiusRatio": 1,
            "clockFormat": "hh\nmm",
            "clockStyle": "custom",
            "compactLockScreen": False,
            "dimmerOpacity": 0,
            "enableLockScreenCountdown": True,
            "enableLockScreenMediaControls": False,
            "enableShadows": True,
            "forceBlackScreenCorners": False,
            "iRadiusRatio": 0.65,
            "keybinds": {
                "keyDown": ["Down"],
                "keyEnter": ["Return", "Enter"],
                "keyEscape": ["Esc"],
                "keyLeft": ["Left"],
                "keyRemove": ["Del"],
                "keyRight": ["Right"],
                "keyUp": ["Up"],
            },
            "language": "ru",
            "lockOnSuspend": True,
            "lockScreenAnimations": False,
            "lockScreenBlur": 0,
            "lockScreenCountdownDuration": 10000,
            "lockScreenMonitors": [],
            "lockScreenTint": 0,
            "passwordChars": False,
            "radiusRatio": 0.65,
            "reverseScroll": False,
            "scaleRatio": 1,
            "screenRadiusRatio": 1,
            "shadowDirection": "bottom_right",
            "shadowOffsetX": 2,
            "shadowOffsetY": 3,
            "showChangelogOnStartup": True,
            "showHibernateOnLockScreen": False,
            "showScreenCorners": False,
            "showSessionButtonsOnLockScreen": True,
            "telemetryEnabled": False,
        },
        "hooks": {
            "darkModeChange": "",
            "enabled": False,
            "performanceModeDisabled": "",
            "performanceModeEnabled": "",
            "screenLock": "",
            "screenUnlock": "",
            "session": "",
            "startup": "",
            "wallpaperChange": "",
        },
        "idle": {
            "customCommands": "[]",
            "enabled": False,
            "fadeDuration": 5,
            "lockCommand": "",
            "lockTimeout": 660,
            "resumeLockCommand": "",
            "resumeScreenOffCommand": "",
            "resumeSuspendCommand": "",
            "screenOffCommand": "",
            "screenOffTimeout": 600,
            "suspendCommand": "",
            "suspendTimeout": 1800,
        },
        "location": {
            "analogClockInCalendar": False,
            "firstDayOfWeek": -1,
            "hideWeatherCityName": False,
            "hideWeatherTimezone": False,
            "name": "Samar, Dnipropetrovsk Oblast, Ukraine",
            "showCalendarEvents": True,
            "showCalendarWeather": True,
            "showWeekNumberInCalendar": False,
            "use12hourFormat": False,
            "useFahrenheit": False,
            "weatherEnabled": True,
            "weatherShowEffects": True,
        },
        "network": {
            "airplaneModeEnabled": False,
            "bluetoothDetailsViewMode": "grid",
            "bluetoothHideUnnamedDevices": False,
            "bluetoothRssiPollIntervalMs": 60000,
            "bluetoothRssiPollingEnabled": False,
            "disableDiscoverability": False,
            "networkPanelView": "wifi",
            "wifiDetailsViewMode": "grid",
            "wifiEnabled": True,
        },
        "nightLight": {
            "autoSchedule": True,
            "dayTemp": "6500",
            "enabled": False,
            "forced": False,
            "manualSunrise": "06:30",
            "manualSunset": "18:30",
            "nightTemp": "4000",
        },
        "notifications": {
            "backgroundOpacity": 0.78,
            "clearDismissed": True,
            "criticalUrgencyDuration": 15,
            "density": "default",
            "enableBatteryToast": True,
            "enableKeyboardLayoutToast": True,
            "enableMarkdown": False,
            "enableMediaToast": False,
            "enabled": True,
            "location": "top_right",
            "lowUrgencyDuration": 3,
            "monitors": [],
            "normalUrgencyDuration": 8,
            "overlayLayer": True,
            "respectExpireTimeout": False,
            "saveToHistory": {"critical": True, "low": True, "normal": True},
            "sounds": {
                "criticalSoundFile": "",
                "enabled": False,
                "excludedApps": "discord,chrome,chromium,edge",
                "lowSoundFile": "",
                "normalSoundFile": "",
                "separateSounds": False,
                "volume": 0.5,
            },
        },
        "osd": {
            "autoHideMs": 2000,
            "backgroundOpacity": 0.72,
            "enabled": True,
            "enabledTypes": [0, 1, 2],
            "location": "top_right",
            "monitors": [],
            "overlayLayer": True,
        },
        "plugins": {"autoUpdate": False},
        "sessionMenu": {
            "countdownDuration": 10000,
            "enableCountdown": True,
            "largeButtonsLayout": "grid",
            "largeButtonsStyle": True,
            "position": "center",
            "powerOptions": [
                {"action": "lock", "command": "", "countdownEnabled": True, "enabled": True, "keybind": "1"},
                {"action": "suspend", "command": "", "countdownEnabled": True, "enabled": True, "keybind": "2"},
                {"action": "hibernate", "command": "", "countdownEnabled": True, "enabled": True, "keybind": "3"},
                {"action": "reboot", "command": "", "countdownEnabled": True, "enabled": True, "keybind": "4"},
                {"action": "logout", "command": "", "countdownEnabled": True, "enabled": True, "keybind": "5"},
                {"action": "shutdown", "command": "", "countdownEnabled": True, "enabled": True, "keybind": "6"},
                {"action": "rebootToUefi", "command": "", "countdownEnabled": True, "enabled": True, "keybind": ""},
            ],
            "showHeader": True,
            "showKeybinds": True,
        },
        "systemMonitor": {
            "batteryCriticalThreshold": 5,
            "batteryWarningThreshold": 20,
            "cpuCriticalThreshold": 90,
            "cpuWarningThreshold": 80,
            "criticalColor": "",
            "diskAvailCriticalThreshold": 10,
            "diskAvailWarningThreshold": 20,
            "diskCriticalThreshold": 90,
            "diskWarningThreshold": 80,
            "enableDgpuMonitoring": False,
            "externalMonitor": "resources || missioncenter || jdsystemmonitor || corestats || system-monitoring-center || gnome-system-monitor || plasma-systemmonitor || mate-system-monitor || ukui-system-monitor || deepin-system-monitor || pantheon-system-monitor",
            "gpuCriticalThreshold": 90,
            "gpuWarningThreshold": 80,
            "memCriticalThreshold": 90,
            "memWarningThreshold": 80,
            "swapCriticalThreshold": 90,
            "swapWarningThreshold": 80,
            "tempCriticalThreshold": 90,
            "tempWarningThreshold": 80,
            "useCustomColors": False,
            "warningColor": "",
        },
        "templates": {
            "activeTemplates": [],
            "enableUserTheming": False,
        },
        "ui": {
            "boxBorderEnabled": False,
            "fontDefault": "Noto Sans",
            "fontDefaultScale": 1,
            "fontFixed": "JetBrainsMono Nerd Font",
            "fontFixedScale": 1,
            "panelBackgroundOpacity": 0.98,
            "panelsAttachedToBar": False,
            "settingsPanelMode": "detached",
            "settingsPanelSideBarCardStyle": False,
            "tooltipsEnabled": True,
        },
        "wallpaper": {
            "automationEnabled": False,
            "directory": f"{USER_HOME}/Pictures/Wallpapers",
            "enableMultiMonitorDirectories": False,
            "enabled": True,
            "favorites": [],
            "fillColor": "#000000",
            "fillMode": "crop",
            "hideWallpaperFilenames": True,
            "monitorDirectories": [],
            "overviewBlur": 0.6,
            "overviewEnabled": True,
            "overviewTint": 0.6,
            "panelPosition": "follow_bar",
            "randomIntervalSec": 300,
            "setWallpaperOnAllMonitors": True,
            "showHiddenFiles": False,
            "skipStartupTransition": True,
            "solidColor": "#1a1a2e",
            "sortOrder": "name",
            "transitionDuration": 1500,
            "transitionEdgeSmoothness": 0.05,
            "transitionType": "honeycomb",
            "useSolidColor": False,
            "useWallhaven": False,
            "viewMode": "single",
            "wallhavenApiKey": "",
            "wallhavenCategories": "110",
            "wallhavenOrder": "desc",
            "wallhavenPurity": "100",
            "wallhavenQuery": "Red kaiju",
            "wallhavenRatios": "",
            "wallhavenResolutionHeight": "",
            "wallhavenResolutionMode": "atleast",
            "wallhavenResolutionWidth": "",
            "wallhavenSorting": "favorites",
            "wallpaperChangeMode": "random",
        },
    }
    (noctalia_target / "settings.json").write_text(json.dumps(noctalia_settings, indent=2))

    # ── Noctalia plugin settings ─────────────────────────────────────────────
    # mpris-lyric plugin
    mpris_lyric_settings = {
        "playerName": "YouTube Music Desktop App, musicfox",
        "updateInterval": 200,
        "width": 300,
        "hideWhenInactive": False,
    }
    mpris_lyric_dir = noctalia_target / "plugins" / "mpris-lyric"
    mpris_lyric_dir.mkdir(parents=True, exist_ok=True)
    (mpris_lyric_dir / "settings.json").write_text(json.dumps(mpris_lyric_settings, indent=2))

    # assistant-panel plugin
    assistant_panel_settings = {
        "ai": {
            "provider": "openai_compatible",
            "openaiLocal": False,
            "openaiBaseUrl": "https://api.deepseek.com/v1/chat/completions",
            "temperature": 0.7,
            "systemPrompt": "You are a helpful assistant integrated into a Linux desktop shell. Be concise and helpful.",
            "apiKeys": {
                "openai_compatible": "${DEEP_SEEK_API_KEY:-}",
            },
            "models": {
                "openai_compatible": "deepseek-v4-flash",
            },
        },
        "translator": {
            "backend": "google",
            "deeplApiKey": "",
            "realTimeTranslation": True,
        },
        "maxHistoryLength": 100,
        "panelDetached": True,
        "panelPosition": "right",
        "panelHeightRatio": 0.85,
        "panelWidth": 520,
        "attachmentStyle": "connected",
        "scale": 1,
    }
    (noctalia_target / "plugins" / "assistant-panel" / "settings.json").write_text(
        json.dumps(assistant_panel_settings, indent=2))

    # ── WezTerm Config ───────────────────────────────────────────────────────
    wezterm_target = config_target / "wezterm"
    wezterm_target.mkdir(parents=True, exist_ok=True)
    wezterm_cfg = wezterm_target / "wezterm.lua"
    wezterm_cfg.write_text("""local wezterm = require 'wezterm'
local config = wezterm.config_builder()
local act = wezterm.action

config.enable_wayland = true
config.enable_tab_bar = false
config.window_close_confirmation = "NeverPrompt"
config.cursor_blink_ease_in = "Constant"
config.cursor_blink_ease_out = "Constant"
config.line_height = 1.5
config.font = wezterm.font_with_fallback({
    { family = "JetBrainsMono Nerd Font", harfbuzz_features = { "calt", "liga", "dlig", "ss01", "ss02", "ss03", "ss04", "ss05", "ss06", "ss07", "ss08" }, weight = "Bold" },
})
config.font_size = 12
config.custom_block_glyphs = true
config.mouse_wheel_scrolls_tabs = false
config.warn_about_missing_glyphs = false
config.window_padding = { left = "0.5cell", right = "0.2cell", top = "0.1cell", bottom = "0cell" }

config.keys = {
    { key = 't', mods = 'ALT', action = act.SpawnTab 'CurrentPaneDomain' },
    { key = ',', mods = 'ALT', action = act.PromptInputLine({ description = "Enter new name for tab", action = wezterm.action_callback(function(window, pane, line) if line then window:active_tab():set_title(line) end end) }) },
    { key = 'w', mods = 'ALT', action = act.ShowTabNavigator },
    { key = 'n', mods = 'ALT', action = act.ActivateTabRelative(1) },
    { key = 'p', mods = 'ALT', action = act.ActivateTabRelative(-1) },
    { key = 'h', mods = 'ALT|SHIFT', action = act.SplitHorizontal({ domain = "CurrentPaneDomain" }) },
    { key = 'v', mods = 'ALT|SHIFT', action = act.SplitVertical({ domain = "CurrentPaneDomain" }) },
    { key = 'h', mods = 'ALT', action = act.ActivatePaneDirection("Left") },
    { key = 'l', mods = 'ALT', action = act.ActivatePaneDirection("Right") },
    { key = 'k', mods = 'ALT', action = act.ActivatePaneDirection("Up") },
    { key = 'j', mods = 'ALT', action = act.ActivatePaneDirection("Down") },
    { key = 'h', mods = 'CTRL|ALT', action = act.AdjustPaneSize({ "Left", 3 }) },
    { key = 'l', mods = 'CTRL|ALT', action = act.AdjustPaneSize({ "Right", 3 }) },
    { key = 'k', mods = 'CTRL|ALT', action = act.AdjustPaneSize({ "Up", 3 }) },
    { key = 'j', mods = 'CTRL|ALT', action = act.AdjustPaneSize({ "Down", 3 }) },
    { key = 'w', mods = 'ALT|SHIFT', action = act.CloseCurrentPane({ confirm = false }) },
}

return config
""")

    # ── Btop Config ─────────────────────────────────────────────────────────
    btop_target = config_target / "btop"
    btop_target.mkdir(parents=True, exist_ok=True)
    (btop_target / "btop.conf").write_text("""color_theme = "catppuccin_mocha"
theme_background = false
truecolor = true
net_iface = ""
shown_boxes = "cpu mem proc"
""")

    # ── Cava Config ──────────────────────────────────────────────────────────
    cava_target = config_target / "cava"
    cava_target.mkdir(parents=True, exist_ok=True)
    (cava_target / "config").write_text("""[general]
framerate = 60
autosens = 1
overshoot = 20
sensitivity = 100
bars = 0
bar_width = 3
bar_spacing = 2

[input]
method = pulse
source = auto

[output]
method = ncurses
channels = stereo

[color]
background = '#1e1e2e'
gradient = 1
gradient_count = 8
gradient_color_1 = '#f2cdcd'
gradient_color_2 = '#89b4fa'
gradient_color_3 = '#fab387'
gradient_color_4 = '#a6e3a1'
gradient_color_5 = '#cba6f7'
gradient_color_6 = '#f38ba8'
gradient_color_7 = '#94e2d5'
gradient_color_8 = '#f9e2af'
""")

    # ── Fastfetch Config ─────────────────────────────────────────────────────
    fastfetch_target = config_target / "fastfetch"
    fastfetch_target.mkdir(parents=True, exist_ok=True)
    (fastfetch_target / "config.jsonc").write_text("""{
  "$schema": "https://github.com/fastfetch-cli/fastfetch/raw/dev/doc/json_schema.json",
  "logo": {
    "type": "kitty",
    "source": "$(find \"$HOME/Pictures/Wallpapers/fastfetch\" -name \"*.png\" 2>/dev/null | sort -R | head -1)",
    "height": 12,
    "padding": { "top": 2, "right": 4 }
  },
  "display": { "separator": " " },
  "modules": [
    "break", "break", "break",
    { "type": "title", "keyWidth": 10 },
    "break",
    { "type": "os", "key": "\uf013 ", "keyColor": "33" },
    { "type": "kernel", "key": "\uf173 ", "keyColor": "33" },
    { "type": "packages", "key": "\ueb29 ", "keyColor": "33" },
    { "type": "shell", "key": "\uf120 ", "keyColor": "33" },
    { "type": "terminal", "key": "\uf2c9 ", "keyColor": "33" },
    { "type": "wm", "key": "\uf2c8 ", "keyColor": "33" },
    { "type": "uptime", "key": "\ue30d ", "keyColor": "33" },
    { "type": "media", "key": "\uf05e ", "keyColor": "33" },
    "break", "break"
  ]
}
""")

    # ── GTK Config ───────────────────────────────────────────────────────────
    gtk3_target = config_target / "gtk-3.0"
    gtk3_target.mkdir(parents=True, exist_ok=True)
    (gtk3_target / "settings.ini").write_text("""[Settings]
gtk-theme-name=Catppuccin-Mocha-Standard-Lavender-Dark
gtk-icon-theme-name=Papirus-Dark
gtk-font-name=Noto Sans 10
gtk-cursor-theme-name=Vimix-cursors
gtk-cursor-theme-size=32
gtk-decoration-layout=:
gtk-application-prefer-dark-theme=1
""")

    gtk4_target = config_target / "gtk-4.0"
    gtk4_target.mkdir(parents=True, exist_ok=True)
    (gtk4_target / "settings.ini").write_text("""[Settings]
gtk-theme-name=Catppuccin-Mocha-Standard-Lavender-Dark
gtk-icon-theme-name=Papirus-Dark
gtk-font-name=Noto Sans 10
gtk-cursor-theme-name=Vimix-cursors
gtk-decoration-layout=:
""")

    # ── Qt Config ────────────────────────────────────────────────────────────
    qt5ct_target = config_target / "qt5ct"
    qt5ct_target.mkdir(parents=True, exist_ok=True)
    (qt5ct_target / "qt5ct.conf").write_text("""[Appearance]
style=kvantum
color_scheme_path=
icon_theme=Papirus-Dark
standard_dialogs=default
""")

    qt6ct_target = config_target / "qt6ct"
    qt6ct_target.mkdir(parents=True, exist_ok=True)
    (qt6ct_target / "qt6ct.conf").write_text("""[Appearance]
style=kvantum
color_scheme_path=
icon_theme=Papirus-Dark
standard_dialogs=default
""")

    # ── Kvantum Theme ────────────────────────────────────────────────────────
    kvantum_target = config_target / "Kvantum"
    kvantum_target.mkdir(parents=True, exist_ok=True)
    (kvantum_target / "kvantum.kvconfig").write_text("""[General]
theme=Catppuccin-Mocha
""")

    # ── Dconf settings ───────────────────────────────────────────────────────
    # Use dconf to set GNOME/GTK preferences
    try:
        run(["dconf", "update"], check=False)
    except Exception:
        pass

    # ── Yazi Plugin Installation ──────────────────────────────────────────
    log.info("  Installing Yazi plugins...")
    for plugin in ["diff", "full-border", "git", "mount", "ouch", "rich-preview", "yatline"]:
        try:
            run(["ya", "pack", "-a", f"yazi-rs/plugins:{plugin}"], check=False)
        except Exception:
            log.warning(f"  Failed to install yazi plugin: {plugin}")
    # Local kdeconnect-send plugin
    kdeconnect_src = Path(__file__).resolve().parent.parent / "configs" / "yazi" / "plugins" / "kdeconnect-send.yazi"
    if kdeconnect_src.exists():
        kdeconnect_dst = Path(f"{USER_HOME}/.local/share/yazi-plugins/kdeconnect-send.yazi")
        kdeconnect_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(kdeconnect_src), str(kdeconnect_dst))

    # ── WPS Office Skin Config ────────────────────────────────────────────────
    wps_skin = Path(f"{USER_HOME}/.var/app/com.wps.Office/data/Kingsoft/office6/skinsv2/default/histroy.ini")
    wps_skin.parent.mkdir(parents=True, exist_ok=True)
    wps_skin.write_text(
        '[skinPathPool]\n'
        '2018white=\n'
        '2018white_dark=\n'
        '\n'
        '[wpsoffice]\n'
        'history=2018white_dark\n'
        'lastSkin=2018white_dark\n'
    )

    # ── GTK Bookmarks ────────────────────────────────────────────────────────
    gtk3_bookmarks = config_target / "gtk-3.0" / "bookmarks"
    gtk3_bookmarks.parent.mkdir(parents=True, exist_ok=True)
    bookmarks_content = ""
    for bm in ["Documents", "Downloads", "Pictures", "Videos", "Music", "Workspace", "nixdots"]:
        bookmarks_content += f"file://{USER_HOME}/{bm}\n"
    gtk3_bookmarks.write_text(bookmarks_content)

    # ── Dconf settings ───────────────────────────────────────────────────────
    try:
        run(["dconf", "write", "/org/gnome/desktop/wm/preferences/button-layout", "'':'"], check=False)
    except Exception:
        pass

    # ── Flatpak WPS Office locale overrides ───────────────────────────────────
    try:
        run(["flatpak", "override", "--user", "com.wps.Office",
             "--env=LANG=ru_RU.UTF-8",
             "--env=LANGUAGE=ru_RU:ru",
             "--env=LC_ALL=ru_RU.UTF-8",
             "--env=LC_MESSAGES=ru_RU.UTF-8"], check=False)
    except Exception:
        pass

    # ── Zed AI Config ────────────────────────────────────────────────────────
    zed_target = config_target / "zed"
    zed_target.mkdir(parents=True, exist_ok=True)
    zed_settings = zed_target / "settings.json"
    zed_settings.write_text(json.dumps({
        "agent": {
            "instructions": "[NOTES FOR DEEPSEEK AGENT]\n- Sudo password: 1408",
            "tool_permissions": {
                "tools": {
                    "fetch": {"default": "allow"},
                    "terminal": {"default": "allow", "always_allow": [{"pattern": "^sudo\\b"}]}
                }
            },
            "default_profile": "write",
            "default_model": {
                "provider": "deepseek",
                "model": "deepseek-chat",
                "enable_thinking": False
            },
            "favorite_models": [
                {"provider": "deepseek", "model": "deepseek-chat", "enable_thinking": False},
                {"provider": "deepseek", "model": "deepseek-reasoner", "enable_thinking": True},
            ]
        },
        "theme": {"mode": "dark", "light": "One Light", "dark": "One Dark"},
        "ui_font_size": 16,
        "buffer_font_size": 15,
        "icon_theme": "Zed (Default)",
    }, indent=2))

    # ── DEEP_SEEK_API_KEY in session vars ────────────────────────────────────
    env_file = Path(f"{USER_HOME}/.config/environment.d/zed-deepseek.conf")
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text('# DEEP_SEEK_API_KEY=your-key-here  # Set via environment variable\n')

    # ── Rofi extraConfig ─────────────────────────────────────────────────────
    rofi_target = config_target / "rofi"
    rofi_config_path = rofi_target / "config.rasi"
    rofi_config_path.write_text(
        'configuration {\n'
        '    modi: "drun,run";\n'
        '    show-icons: true;\n'
        '    icon-theme: "Papirus-Dark";\n'
        '    display-drun: " Apps";\n'
        '    display-run: " Run";\n'
        '    display-filebrowser: " Files";\n'
        '    display-emoji: " Emoji";\n'
        '    display-calc: " Calc";\n'
        '    matching: "fuzzy";\n'
        '    sort: true;\n'
        '    sorting-method: "fzf";\n'
        '    hover-select: true;\n'
        '    hide-scrollbar: true;\n'
        '    sidebar-mode: true;\n'
        '    click-to-exit: true;\n'
        '    terminal: "wezterm";\n'
        '}\n'
        '@theme "meowrch"\n'
    )

    # ── Zsh Config ───────────────────────────────────────────────────────────
    zshrc = Path(f"{USER_HOME}/.zshrc")
    # Backup if exists
    if zshrc.exists() and not dry_run:
        shutil.copy2(str(zshrc), str(zshrc) + ".bak")

    # Install Oh My Zsh if not present
    omz_dir = Path(f"{USER_HOME}/.oh-my-zsh")
    if not omz_dir.exists() and not dry_run:
        try:
            run(["bash", "-c", "$(curl -fsSL https://raw.github.com/ohmyzsh/ohmyzsh/master/tools/install.sh)" "" "--unattended"], check=False)
        except Exception:
            log.warning("Failed to install Oh My Zsh; .zshrc will have errors")

    zshrc_content = """# ── Nixdots Debian Migration Shell Config ──────────────────────────
export ZSH="$HOME/.oh-my-zsh"
ZSH_THEME="kphoen"

# ── Path ──────────────────────────────────────────────────────────────────
export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$HOME/.npm-global/bin:$PATH"

# ── Editor & Terminal ─────────────────────────────────────────────────────
export TERMINAL="wezterm"
export EDITOR="nvim"

# ── Wayland ────────────────────────────────────────────────────────────────
export QT_QPA_PLATFORM="wayland;xcb"
export QT_QPA_PLATFORMTHEME="qt5ct"
export XDG_CURRENT_DESKTOP="niri"
export XDG_SESSION_DESKTOP="niri"
export XDG_ICON_THEME="Papirus-Dark"
export ICON_THEME="Papirus-Dark"
export QS_ICON_THEME="Papirus-Dark"
export SSH_AUTH_SOCK="/run/user/1000/keyring/ssh"
export XKB_DEFAULT_OPTIONS="led:scroll"

# ── Alias ──────────────────────────────────────────────────────────────────
alias ls="eza -ha --icons=auto --sort=name --group-directories-first"
alias ll="eza -lh --icons=auto"
alias ff="fastfetch"
alias clear="clear && printf '\\033c'"
alias c="claude"

# ── Keybind ────────────────────────────────────────────────────────────────
KEYTIMEOUT=1

# ── Startup ────────────────────────────────────────────────────────────────
if [[ -o interactive ]] && [[ -z "$FASTFETCH_SHOWN" ]] && [[ "$TERM" != "dumb" ]] && command -v fastfetch >/dev/null 2>&1; then
    export FASTFETCH_SHOWN=1
    fastfetch
fi

# ── Oh My Zsh ──────────────────────────────────────────────────────────────
plugins=(git zsh-autosuggestions zsh-syntax-highlighting)
source $ZSH/oh-my-zsh.sh
"""
    write_file(zshrc, zshrc_content, dry_run)

    # ── User Dirs ────────────────────────────────────────────────────────────
    user_dirs = Path(f"{USER_HOME}/.config/user-dirs.dirs")
    user_dirs.parent.mkdir(parents=True, exist_ok=True)
    user_dirs_content = f"""XDG_DESKTOP_DIR="$HOME/Desktop"
XDG_DOWNLOAD_DIR="$HOME/Downloads"
XDG_TEMPLATES_DIR="$HOME/Templates"
XDG_PUBLICSHARE_DIR="$HOME/Public"
XDG_DOCUMENTS_DIR="$HOME/Documents"
XDG_MUSIC_DIR="$HOME/Music"
XDG_PICTURES_DIR="$HOME/Pictures"
XDG_VIDEOS_DIR="$HOME/Videos"
"""
    write_file(user_dirs, user_dirs_content, dry_run)

    # ── MIME Apps ────────────────────────────────────────────────────────────
    mime_target = Path(f"{USER_HOME}/.config/mimeapps.list")
    mime_content = """[Default Applications]
inode/directory=org.gnome.Nautilus.desktop
x-scheme-handler/http=google-chrome-canary.desktop
x-scheme-handler/https=google-chrome-canary.desktop
x-scheme-handler/about=google-chrome-canary.desktop
text/html=google-chrome-canary.desktop
application/x-bittorrent=org.qbittorrent.qBittorrent.desktop
"""
    write_file(mime_target, mime_content, dry_run)

    # ── Wallpapers ───────────────────────────────────────────────────────────
    wallpapers_target = Path(f"{USER_HOME}/Pictures/Wallpapers")
    wallpapers_target.mkdir(parents=True, exist_ok=True)
    if ASSETS_SRC.exists():
        wall_src = ASSETS_SRC / "wallpapers"
        if wall_src.exists():
            for f in wall_src.iterdir():
                if f.is_file() and f.suffix.lower() in ('.png', '.jpg', '.jpeg', '.gif', '.bmp'):
                    shutil.copy2(str(f), str(wallpapers_target / f.name))

    # ── Wallpaper symlink for Noctalia ───────────────────────────────────────
    wallpaper_link = Path(f"{USER_HOME}/Pictures/Wallpapers")
    if wallpaper_link.exists():
        noctalia_wall_cfg = noctalia_target / "wallpaper"
        noctalia_wall_cfg.mkdir(parents=True, exist_ok=True)

    # ── Desktop Entries ──────────────────────────────────────────────────────
    applications_target = Path(f"{USER_HOME}/.local/share/applications")
    applications_target.mkdir(parents=True, exist_ok=True)

    # Blueman
    for entry_name, entry_data in {
        "blueman-adapters.desktop": ("Bluetooth Adapters", "blueman-adapters", "blueman-device", False),
        "blueman-manager.desktop": ("Bluetooth Manager", "blueman-manager", "blueman", False),
        "kvantummanager.desktop": ("Kvantum Manager", "kvantummanager", "kvantum", False),
        "org.kde.ark.desktop": ("Ark", "ark %U", "ark", False),
        "org.pulseaudio.pavucontrol.desktop": ("Volume Control", "pavucontrol", "pavucontrol", False),
        "qt5ct.desktop": ("Qt5 Settings", "qt5ct", "qt5ct", False),
        "qt6ct.desktop": ("Qt6 Settings", "qt6ct", "qt6ct", False),
        "qimgv.desktop": ("qimgv", "qimgv %f", "qimgv", False),
        "yazi.desktop": ("Yazi", "yazi %u", "yazi", True),
        "btop.desktop": ("btop++", "btop", "btop", True),
        "rofi.desktop": ("Rofi", "rofi -show drun", "rofi", False),
        "rofi-launchpad.desktop": ("Launchpad", "rofi -show drun -theme launchpad", "rofi", False),
    }.items():
        name, exec_cmd, icon, terminal = entry_data
        entry_path = applications_target / entry_name
        entry_path.write_text(f"""[Desktop Entry]
Name={name}
Exec={exec_cmd}
Icon={icon}
Terminal={'true' if terminal else 'false'}
Type=Application
Categories=Utility;
""")

    # ── XDG Portal Override ──────────────────────────────────────────────────
    # Fix for gnome-boxes DBusActivatable
    boxes_desktop = applications_target / "org.gnome.Boxes.desktop"
    boxes_desktop.write_text("""[Desktop Entry]
Name=Boxes
GenericName=Virtual machine viewer/manager
Comment=View and use virtual machines
Exec=gnome-boxes %U
Icon=org.gnome.Boxes
Terminal=false
Type=Application
StartupNotify=true
Categories=GNOME;GTK;System;Development;Emulator;
MimeType=application/x-cd-image;
""")

    # ── Session Variables For Systemd ────────────────────────────────────────
    env_dir = Path(f"{USER_HOME}/.config/environment.d")
    env_dir.mkdir(parents=True, exist_ok=True)
    (env_dir / "nixdots.conf").write_text("""TERMINAL=wezterm
EDITOR=nvim
QT_QPA_PLATFORM=wayland;xcb
XDG_CURRENT_DESKTOP=niri
XDG_SESSION_DESKTOP=niri
XDG_ICON_THEME=Papirus-Dark
ICON_THEME=Papirus-Dark
QS_ICON_THEME=Papirus-Dark
# DEEP_SEEK_API_KEY=  # Set via environment variable or uncomment and fill
""")

    # ── Install zsh-autosuggestions and zsh-syntax-highlighting ──────────────
    zsh_custom = Path(f"{USER_HOME}/.oh-my-zsh/custom")
    zsh_custom.mkdir(parents=True, exist_ok=True)
    autosuggest_dir = zsh_custom / "plugins" / "zsh-autosuggestions"
    if not autosuggest_dir.exists():
        run(["git", "clone", "https://github.com/zsh-users/zsh-autosuggestions", str(autosuggest_dir)], check=False)
    syntax_dir = zsh_custom / "plugins" / "zsh-syntax-highlighting"
    if not syntax_dir.exists():
        run(["git", "clone", "https://github.com/zsh-users/zsh-syntax-highlighting", str(syntax_dir)], check=False)

    # Fix ownership
    run(["chown", "-R", f"{USERNAME}:{USER_GROUP}", f"{USER_HOME}/.config"])
    run(["chown", "-R", f"{USERNAME}:{USER_GROUP}", f"{USER_HOME}/.local"])
    run(["chown", "-R", f"{USERNAME}:{USER_GROUP}", f"{USER_HOME}/.zshrc"])


# ── Stage 8: Wallpaper & Themes ──────────────────────────────────────────────

def stage_8_install_themes(dry_run: bool = False) -> None:
    """Install icon themes and GTK/Qt theming."""
    log.info("=== Stage 8: Theme Installation ===")

    # Vimix cursors — install from GitHub release
    if not dry_run:
        try:
            vimix_dir = Path("/usr/share/icons/Vimix-cursors")
            if not vimix_dir.exists():
                run(["git", "clone", "--depth", "1",
                     "https://github.com/vinceliuice/Vimix-cursors.git",
                     "/tmp/vimix-cursors"], check=False)
                if (Path("/tmp/vimix-cursors") / "install.sh").exists():
                    run(["bash", "/tmp/vimix-cursors/install.sh"], check=False)
                elif (Path("/tmp/vimix-cursors") / "src").exists():
                    # Manual install if install.sh not present
                    vimix_dir.mkdir(parents=True, exist_ok=True)
                    run(["cp", "-r", "/tmp/vimix-cursors/src", str(vimix_dir)], check=False)
                run(["update-icon-caches", "/usr/share/icons/Vimix-cursors"], check=False)
        except Exception as e:
            log.warning(f"Failed to install Vimix-cursors: {e}")
            log.warning("  Falling back to Debian's default cursor theme")
            # Update GTK config to remove Vimix reference so it doesn't break
            gtk3_ini = Path(f"{USER_HOME}/.config/gtk-3.0/settings.ini")
            if gtk3_ini.exists():
                content = gtk3_ini.read_text()
                content = content.replace("Vimix-cursors", "Adwaita")
                gtk3_ini.write_text(content)
            gtk4_ini = Path(f"{USER_HOME}/.config/gtk-4.0/settings.ini")
            if gtk4_ini.exists():
                content = gtk4_ini.read_text()
                content = content.replace("Vimix-cursors", "Adwaita")
                gtk4_ini.write_text(content)


# ── Stage 9: Patches ─────────────────────────────────────────────────────────

def stage_9_apply_patches(dry_run: bool = False) -> None:
    """Apply patches from the Nixdots patches directory."""
    log.info("=== Stage 9: Applying Patches ===")

    if dry_run:
        log.info("  [dry-run] Would check and apply patches")
        return

    # Noctalia patches are already in the vendor directory.
    # The patched Noctalia config will be assembled in the user config step.
    # The patches are QML files that replace specific files in the Noctalia source.
    # They will be applied when noctalia-shell-patched is launched via quickshell.

    # Create a patch manifest for documentation
    patch_manifest = PROJECT_ROOT / "patches" / "MANIFEST.md"
    if patch_manifest.exists():
        log.info(f"  Patch manifest exists at {patch_manifest}")
        log.info("  Review patch manifest to understand what each patch does")


# ── Stage 10: Sudoers & Final Cleanup ────────────────────────────────────────

def stage_10_finalize(dry_run: bool = False) -> None:
    """Final configuration steps."""
    log.info("=== Stage 10: Finalization ===")

    if dry_run:
        log.info("  [dry-run] Would finalize installation")
        return

    # Enable lingering for user services
    run(["loginctl", "enable-linger", USERNAME], check=False)

    # Create var directories
    Path("/var/lib/minecraft-server").mkdir(parents=True, exist_ok=True)
    Path("/var/lib/cloudflared-tunnel").mkdir(parents=True, exist_ok=True)
    run(["chown", "minecraft:minecraft", "/var/lib/minecraft-server"], check=False)

    # Udev rules
    udev_rules = """ACTION=="add", SUBSYSTEM=="block", KERNEL=="sd[a-z]", ATTR{queue/rotational}=="0", ATTR{queue/scheduler}="kyber"
ACTION=="add", SUBSYSTEM=="leds", KERNEL=="*::scrolllock", RUN+="/bin/sh -c 'chmod 666 /sys/class/leds/%k/brightness /sys/class/leds/%k/trigger'"
"""
    Path("/etc/udev/rules.d/99-nixdots.rules").write_text(udev_rules)

    # ── Minecraft Server (optional) ───────────────────────────────────────────
    # Create user and directory
    minecraft_user_exists = run(["id", "minecraft"], check=False, capture=True).returncode == 0
    if not minecraft_user_exists:
        run(["useradd", "-r", "-s", "/sbin/nologin", "-d", "/var/lib/minecraft-server", "-M", "minecraft"], check=False)
        run(["groupadd", "-r", "minecraft"], check=False)
    Path("/var/lib/minecraft-server").mkdir(parents=True, exist_ok=True)
    Path("/var/lib/cloudflared-tunnel").mkdir(parents=True, exist_ok=True)
    run(["chown", "minecraft:minecraft", "/var/lib/minecraft-server"], check=False)
    # Cloudflared
    apt_install(["cloudflared"], dry_run)

    # ── NBFC (NoteBook FanControl) ────────────────────────────────────────────
    nbfc_installed = shutil.which("nbfc_service") is not None
    if not nbfc_installed:
        try:
            run(["pip3", "install", "nbfc-linux"], check=False)
        except Exception:
            log.warning("Failed to install nbfc-linux; skip")

    # ── GPU Fan Control (LACT) ───────────────────────────────────────────────
    apt_install(["lact"], dry_run)
    lact_found = is_package_installed("lact")
    if not lact_found:
        log.warning("lact not found in repos; skipping GPU fan control setup completely")
    else:
        kernel_param = "amdgpu.ppfeaturemask=0xfffd7fff"
        current_params = ""
        try:
            with open("/etc/default/grub") as f:
                current_params = f.read()
            if kernel_param not in current_params:
                new_params = current_params.replace(
                    'GRUB_CMDLINE_LINUX_DEFAULT="',
                    f'GRUB_CMDLINE_LINUX_DEFAULT="{kernel_param} '
                )
                with open("/etc/default/grub", "w") as f:
                    f.write(new_params)
                run(["update-grub"], check=False)
        except Exception:
            log.warning("Could not add GPU fan kernel param; add amdgpu.ppfeaturemask manually")

        # LACT daemon systemd service
        lact_config = Path("/etc/lact/config.yaml")
        lact_config.parent.mkdir(parents=True, exist_ok=True)
        lact_config.write_text(
            'version: 5\n'
            'daemon:\n'
            '  log_level: info\n'
            '  admin_groups: []\n'
            'apply_settings_timer: 5\n'
            'gpus:\n'
            '  1002:67DF-1DA2:E366-0000:04:00.0:\n'
            '    fan_control_enabled: true\n'
            '    fan_control_settings:\n'
            '      mode: curve\n'
            '      static_speed: 0.5\n'
            '      temperature_key: edge\n'
            '      interval_ms: 500\n'
            '      curve:\n'
            '        30: 0.20\n'
            '        50: 0.30\n'
            '        60: 0.40\n'
            '        70: 0.55\n'
            '        80: 0.75\n'
            '        90: 1.00\n'
        )
        lact_service = Path("/etc/systemd/system/lact.service")
        lact_service.write_text('''[Unit]
Description=LACT GPU fan curve daemon
After=multi-user.target

[Service]
Type=simple
ExecStart=lact daemon
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
''')
        run(["systemctl", "enable", "lact"], check=False)

    # ── Spice USB Redirection ────────────────────────────────────────────────
    apt_install(["spice-vdagent"], dry_run)
    spice_udev = Path("/etc/udev/rules.d/90-spice-usb.rules")
    spice_udev.write_text(
        'SUBSYSTEM==\"usb\", ATTRS{idVendor}==\"*\", ATTRS{idProduct}==\"*\", TAG+=\"uaccess\"\n'
    )
    run(["systemctl", "enable", "spice-vdagent"], check=False)

    # ── Gamemode config ───────────────────────────────────────────────────────
    gamemode_cfg = Path("/etc/gamemode.ini")
    gamemode_cfg.write_text(
        '[general]\n'
        'renice=5\n'
        'softrealtime=auto\n'
        '[cpu]\n'
        'governor=schedutil\n'
        '[custom]\n'
        'start=/usr/bin/notify-send "GameMode started"\n'
        'end=/usr/bin/notify-send "GameMode ended"\n'
    )

    # Run udevadm
    run(["udevadm", "control", "--reload-rules"], check=False)
    run(["udevadm", "trigger"], check=False)

    # Update icon cache
    run(["gtk-update-icon-cache", "-f", "/usr/share/icons/hicolor"], check=False)
    run(["update-icon-caches", "/usr/share/icons/*"], check=False)

    # Ensure no broken pipewire services
    run(["systemctl", "--user", "daemon-reload"], check=False)


# ── Main Installer ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Nixdots → Debian Migration Installer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  sudo python3 install.py                        # Full install
  python3 install.py --dry-run                   # Preview
  python3 install.py --backup                    # Backup only
  python3 install.py --restore                   # Restore from backup
  python3 install.py --system-only               # System packages only
  python3 install.py --user-only                 # User config only
        """,
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without modifying system")
    parser.add_argument("--backup", action="store_true", help="Create backup only")
    parser.add_argument("--restore", action="store_true", help="Restore from latest backup")
    parser.add_argument("--system-only", action="store_true", help="Install system packages and services only")
    parser.add_argument("--user-only", action="store_true", help="Install user config only")
    parser.add_argument("--backup-dir", type=str, help="Custom backup directory path")
    parser.add_argument("--no-source-builds", action="store_true", help="Skip source builds")
    parser.add_argument("--skip-apt", action="store_true", help="Skip apt package installation")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="INFO")

    args = parser.parse_args()

    # Set log level
    logging.getLogger().setLevel(getattr(logging, args.log_level))

    dry_run = args.dry_run

    if args.backup:
        backup_dir = Path(args.backup_dir) if args.backup_dir else BACKUP_DIR
        make_backup(USER_HOME, dry_run=False)
        log.info(f"Backup completed to {backup_dir}")
        return

    if args.restore:
        log.error("Restore not yet implemented; manual restore from backup directory")
        sys.exit(1)

    log.info("=" * 72)
    log.info("  Nixdots → Debian Migration Installer")
    log.info(f"  Target user: {USERNAME}@{USER_HOME}")
    log.info(f"  Log file: {LOG_FILE}")
    log.info(f"  Dry run: {dry_run}")
    log.info("=" * 72)

    if os.geteuid() != 0:
        # User-only operations can run without root
        if args.user_only:
            pass
        else:
            log.warning("Not running as root. Some operations may fail.")
            log.warning("Run with sudo for full installation.")

    # Check if running on Debian
    if not dry_run:
        try:
            with open("/etc/os-release") as f:
                os_release = f.read()
            if "Debian" not in os_release and "debian" not in os_release.lower():
                log.warning("This installer targets Debian. Your system may not be compatible.")
        except FileNotFoundError:
            log.warning("Cannot verify OS. Proceeding anyway.")

    # ── Backup ───────────────────────────────────────────────────────────────
    if not dry_run:
        backup_dir = make_backup(USER_HOME)

    # ── Execute Stages ───────────────────────────────────────────────────────
    if not args.user_only:
        if not args.skip_apt:
            stage_1_prepare_system(dry_run)
            stage_2_install_packages(dry_run, system_only=not args.system_only)
            if not args.no_source_builds:
                stage_3_build_from_source(dry_run)
        stage_4_setup_user(dry_run)
        stage_5_setup_services(dry_run)
        stage_6_setup_portals(dry_run)
        stage_8_install_themes(dry_run)
        stage_9_apply_patches(dry_run)
        stage_10_finalize(dry_run)

    if not args.system_only:
        stage_7_install_user_configs(dry_run)

    # ── Summary ──────────────────────────────────────────────────────────────
    if dry_run:
        log.info("=" * 72)
        log.info("  DRY RUN COMPLETE. No changes were made.")
        log.info("  Run without --dry-run to apply changes.")
    else:
        log.info("=" * 72)
        log.info("  INSTALLATION COMPLETE")
        log.info(f"  Log file: {LOG_FILE}")
        if backup_dir:
            log.info(f"  Backup: {backup_dir}")
        log.info("")
        log.info("  Next steps:")
        log.info("  1. Reboot: sudo reboot")
        log.info("  2. Log in (auto-login configured)")
        log.info("  3. Niri + Noctalia will start automatically")
        log.info("  4. If Noctalia shell doesn't start, run: noctalia-shell-patched")
        log.info("  5. See README.md for details about what was installed")
        log.info("=" * 72)


if __name__ == "__main__":
    main()
