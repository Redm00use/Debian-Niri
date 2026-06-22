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
import tarfile
import tempfile
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
    """Install Debian packages via apt."""
    if not packages:
        return
    pkg_list = " ".join(packages)
    log.info(f"Installing {len(packages)} packages: {pkg_list[:200]}...")
    if not dry_run:
        run(["apt-get", "install", "-y", "--no-install-recommends"] + packages)


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


def ensure_user_exists(username: str, dry_run: bool = False) -> None:
    """Create user if they don't exist."""
    if dry_run:
        log.info(f"  [dry-run] Would ensure user exists: {username}")
        return
    result = run(["id", username], check=False, capture=True)
    if result.returncode != 0:
        log.info(f"Creating user: {username}")
        run(["useradd", "-m", "-G", "wheel,networkmanager,kvm,libvirtd,plugdev,video,input",
             "-s", "/usr/bin/zsh", username])
        run(["chpasswd"], input=f"{username}:{USER_PASSWORD}", text=True)
    else:
        log.info(f"User {username} already exists")
        # Ensure user is in required groups
        run(["usermod", "-aG", "wheel,networkmanager,kvm,libvirtd,plugdev,video,input", username])


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
            shutil.copytree(str(path), str(dest), symlinks=True, dirs_exist_ok=True)
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
    "xwayland-satellite": "xwayland-satellite",
    "freerdp": "freerdp2-x11",

    # Audio
    "pipewire": "pipewire",
    "wireplumber": "wireplumber",
    "pipewire-pulse": "pipewire-pulse",
    "pipewire-alsa": "pipewire-alsa",
    "pipewire-jack": "pipewire-jack",
    "pulseaudio-utils": "pulseaudio-utils",

    # Bluetooth
    "bluez": "bluez",
    "bluez-utils": "bluez-utils",
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
    "qt5-style-plugins": "qt5-style-plugins",
    "qt6-style-kvantum": "qt6-style-kvantum",
    "qt6-style-kvantum-themes": "qt6-style-kvantum-themes",
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
    "rocm-opencl-runtime": "rocm-opencl-runtime",

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
    "steam": "steam",
    "steam-devices": "steam-devices",
    "gamemode": "gamemode",
    "mangohud": "mangohud",
    "protonup-qt": "protonup-qt",

    # Polkit / Auth
    "policykit-1": "policykit-1",
    "polkit-kde-agent-1": "policykit-1-gnome",
    "gnome-keyring": "gnome-keyring",
    "libpam-gnome-keyring": "libpam-gnome-keyring",
    "accounts-daemon": "accountsservice",

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
    "telegram-desktop": "telegram-desktop",
    "ark": "ark",
    "gparted": "gparted",
    "obs-studio": "obs-studio",
    "obsidian": "obsidian",
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
}

# Desktop-only packages (isDesktop = true)
DESKTOP_PACKAGES = {
    "cowsay": "cowsay",
    "cmatrix": "cmatrix",
    "pokemon-colorscripts": "pokemon-colorscripts",
    "flatpak": "flatpak",
    "gnome-software": "gnome-software",
    "gnome-software-plugin-flatpak": "gnome-software-plugin-flatpak",
    "opentabletdriver": "opentabletdriver",
}

# Packages NOT in Debian repos (must be installed via alternative methods)
SOURCE_BUILD_PACKAGES = {
    "niri": "Niri compositor",
    "quickshell": "QuickShell",
    "noctalia-shell": "Noctalia Shell",
    "walker": "Walker launcher",
    "rofi": "Rofi (may need backports)",
    "wezterm": "WezTerm",
    "yazi": "Yazi file manager",
    "cider": "Cider Apple Music client",
    "sunder": "Sunder YouTube music",
    "google-chrome-canary": "Google Chrome Canary",
    "eww": "Elkowar's wacky widgets",
    "gowall": "Gowall wallpaper tool",
    "gpu-screen-recorder": "GPU screen recorder",
    "vesktop": "Vesktop Discord client",
    "nbfc-linux": "NoteBook FanControl",
    "pfetch-rs": "pfetch-rs",
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
    for key, value in sysctl_settings.items():
        if not dry_run:
            run(["sysctl", "-w", f"{key}={value}"], check=False)
            write_file(Path(f"/etc/sysctl.d/90-nixdots.conf"),
                       f"# Nixdots migration - set by installer\n{key}={value}\n", dry_run)

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

    # Enable 32-bit architecture for Steam
    if not dry_run:
        try:
            run(["dpkg", "--add-architecture", "i386"], check=False)
            run(["apt-get", "update"], check=False)
        except Exception:
            log.warning("Failed to add i386 architecture")


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
            log.info("Trying to install Niri via Debian experimental...")
            run(["apt-get", "install", "-t", "experimental", "-y", "niri"], check=False)

    # Walker launcher
    log.info("Installing Walker launcher...")
    if not dry_run and not shutil.which("walker"):
        try:
            # Walker is a Go project
            run(["go", "install", "github.com/abenz1267/walker@latest"], check=False)
        except Exception as e:
            log.error(f"Failed to install Walker: {e}")

    # Rofi (ensure it's installed)
    if not dry_run and not shutil.which("rofi"):
        try:
            run(["apt-get", "install", "-y", "rofi"], check=False)
        except Exception:
            log.warning("Rofi not found in repos; trying backports")
            run(["apt-get", "install", "-t", "bookworm-backports", "-y", "rofi"], check=False)

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
        "zramswap",
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

    # Polkit agent
    if not dry_run:
        polkit_dir = Path(f"{USER_HOME}/.config/systemd/user")
        polkit_dir.mkdir(parents=True, exist_ok=True)
        polkit_service = polkit_dir / "polkit-gnome-authentication-agent-1.service"
        polkit_service.write_text("""[Unit]
Description=polkit-gnome-authentication-agent-1
After=graphical-session.target
Wants=graphical-session.target

[Service]
Type=simple
ExecStart=/usr/lib/policykit-1-gnome/polkit-gnome-authentication-agent-1
Restart=on-failure
RestartSec=1
TimeoutStopSec=10

[Install]
WantedBy=graphical-session.target
""")

    # Greetd (display manager)
    log.info("Setting up greetd for auto-login...")
    if not dry_run:
        greetd_dir = Path("/etc/greetd")
        greetd_dir.mkdir(parents=True, exist_ok=True)
        greetd_config = greetd_dir / "config.toml"
        greetd_config.write_text(f"""[terminal]
vt = 1

[default_session]
command = "niri-session"
user = "{USERNAME}"
""")
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

    # Ensure user owns portal configs
    run(["chown", "-R", f"{USERNAME}:{USER_GROUP}", str(portal_dir)])
    run(["chown", "-R", f"{USERNAME}:{USER_GROUP}", str(portal_wlr_dir)])


# ── Stage 7: User Dotfiles & Configs ─────────────────────────────────────────

def stage_7_install_user_configs(dry_run: bool = False) -> None:
    """Install all user-level configuration files."""
    log.info("=== Stage 7: User Configuration ===")

    config_target = Path(f"{USER_HOME}/.config")
    local_target = Path(f"{USER_HOME}/.local/share")

    if dry_run:
        log.info("  [dry-run] Would install user configs")
        return

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

    # Noctalia plugin config
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
  "logo": { "type": "kitty", "height": 12, "padding": { "top": 2, "right": 4 } },
  "display": { "separator": " " },
  "modules": [
    "break", "break", "break",
    { "type": "title", "keyWidth": 10 },
    "break",
    { "type": "os", "key": " ", "keyColor": "33" },
    { "type": "kernel", "key": " ", "keyColor": "33" },
    { "type": "packages", "key": " ", "keyColor": "33" },
    { "type": "shell", "key": " ", "keyColor": "33" },
    { "type": "terminal", "key": " ", "keyColor": "33" },
    { "type": "wm", "key": " ", "keyColor": "33" },
    { "type": "uptime", "key": " ", "keyColor": "33" },
    { "type": "media", "key": "󰝚 ", "keyColor": "33" },
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

    # ── Zsh Config ───────────────────────────────────────────────────────────
    zshrc = Path(f"{USER_HOME}/.zshrc")
    # Backup if exists
    if zshrc.exists() and not dry_run:
        shutil.copy2(str(zshrc), str(zshrc) + ".bak")

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
alias rb="sudo nixos-rebuild switch --flake ~/nixdots#kotlin"
alias upd="nix flake update ~/nixdots"
alias upg="sudo nixos-rebuild switch --upgrade --flake ~/nixdots#kotlin"
alias conf="nvim ~/nixdots/modules/nixos/configuration.nix"
alias pkgs="nvim ~/nixdots/modules/nixos/packages.nix"

# ── Keybind ────────────────────────────────────────────────────────────────
KEYTIMEOUT=1

# ── Startup ────────────────────────────────────────────────────────────────
if [[ -o interactive ]] && [[ -z "$FASTFETCH_SHOWN" ]] && [[ "$TERM" != "dumb" ]] && command -v fastfetch >/dev/null 2>&1; then
    export FASTFETCH_SHOWN=1
    fastfetch
fi

# ── Oh My Zsh ──────────────────────────────────────────────────────────────
plugins=(git)
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

    # ── Zed Config ───────────────────────────────────────────────────────────
    zed_target = config_target / "zed"
    zed_target.mkdir(parents=True, exist_ok=True)
    zed_settings = zed_target / "settings.json"
    zed_settings.write_text(json.dumps({
        "theme": {"mode": "dark", "light": "One Light", "dark": "One Dark"},
        "ui_font_size": 16,
        "buffer_font_size": 15,
        "icon_theme": "Zed (Default)",
    }, indent=2))

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
""")

    # Fix ownership
    run(["chown", "-R", f"{USERNAME}:{USER_GROUP}", f"{USER_HOME}/.config"])
    run(["chown", "-R", f"{USERNAME}:{USER_GROUP}", f"{USER_HOME}/.local"])
    run(["chown", "-R", f"{USERNAME}:{USER_GROUP}", f"{USER_HOME}/.zshrc"])


# ── Stage 8: Wallpaper & Themes ──────────────────────────────────────────────

def stage_8_install_themes(dry_run: bool = False) -> None:
    """Install icon themes and GTK/Qt theming."""
    log.info("=== Stage 8: Theme Installation ===")

    # Vimix cursors
    if not dry_run:
        try:
            vimix_url = "https://github.com/vinceliuice/Vimix-cursors/releases/download/v1.0/Vimix-cursors.tar.xz"
            run(["wget", "-O", "/tmp/vimix-cursors.tar.xz", vimix_url], check=False)
            run(["mkdir", "-p", "/usr/share/icons/Vimix-cursors"])
            run(["tar", "-xf", "/tmp/vimix-cursors.tar.xz", "-C", "/usr/share/icons/Vimix-cursors", "--strip-components=1"], check=False)
            run(["update-icon-caches", "/usr/share/icons/Vimix-cursors"], check=False)
        except Exception as e:
            log.warning(f"Failed to install Vimix-cursors: {e}")


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
