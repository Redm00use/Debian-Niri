# Nixdots → Debian Migration

Rebuilds the **Niri + Noctalia** desktop environment from the Nixdots NixOS
configuration on a minimal Debian base system.

---

## What This Is

This project is a complete migration of the
[Redm00use/Nixdots](https://github.com/Redm00use/Nixdots) NixOS configuration
to Debian. It takes a bare minimal Debian install (no desktop, no WM, no shell
customization) and turns it into the same Niri + Noctalia desktop that the
original NixOS setup provides.

---

## Repository Structure

```
Debian/
├── README.md               # This file
├── AUDIT_REPORT.md          # Full repository audit and migration mapping
├── install.py               # Python installer (main entry point)
├── installer/
│   ├── install.py           # Main installer script
│   └── modules/             # Installer module helpers (future)
├── configs/                 # Static config files (1:1 copies from Nixdots)
│   ├── niri/
│   │   └── config.kdl       # Niri WM config with all keybindings
│   ├── rofi/                # Rofi themes (meowrch, launchpad, emoji)
│   ├── walker/              # Walker launcher config + themes
│   ├── yazi/                # Yazi init.lua
│   └── noctalia/            # Noctalia settings (optional)
├── patches/
│   ├── MANIFEST.md          # Patch documentation
│   └── noctalia/            # 6 QML patch files for Noctalia
├── vendor/
│   └── noctalia/plugins/    # 6 vendored Noctalia plugins
├── assets/
│   ├── profile.png          # User avatar
│   └── wallpapers/          # 60+ wallpapers
├── system/                  # System-level config templates (future)
├── user/                    # User-level config templates (future)
└── scripts/                 # Helper scripts
```

---

## Quick Start

### Prerequisites

1. **Debian minimal install** (no desktop environment)
2. **Root access** (sudo)
3. **Internet connection**

### Installation

```bash
# Clone or copy this project to the target machine
# Then run as root:
sudo python3 installer/install.py

# Or copy the single-file installer:
sudo python3 installer/install.py --system-only
```

### Installation Options

```bash
# Full installation (system + user configs)
sudo python3 installer/install.py

# System-only: packages, services, portals
sudo python3 installer/install.py --system-only

# User-only: dotfiles, configs, themes (no root needed)
python3 installer/install.py --user-only

# Dry run (preview without changes)
python3 installer/install.py --dry-run

# Skip source builds
sudo python3 installer/install.py --no-source-builds

# Create backup only
python3 installer/install.py --backup

# Custom log level
sudo python3 installer/install.py --log-level=DEBUG
```

---

## What the Installer Does

The installer runs in 10 stages:

| Stage | What | Details |
|-------|------|---------|
| **1** | System Preparation | Kernel sysctl, DNS, timezone, locale, keymap, i386 arch |
| **2** | Package Installation | 120+ Debian packages via apt |
| **3** | Source Builds | WezTerm, Yazi, Niri, Walker, Eww, Chrome Canary from source/.deb |
| **4** | User Setup | Create user `kotlin`, groups, directories, profile picture |
| **5** | System Services | NetworkManager, bluetooth, cups, pipewire, greetd, libvirtd, etc. |
| **6** | Portal Configuration | XDG Desktop Portal for Niri (wlr + gtk) |
| **7** | User Configs | Niri, Rofi, Walker, Yazi, WezTerm, Zsh, GTK, Qt, wallpapers |
| **8** | Theme Installation | Vimix cursors, icon caches |
| **9** | Patches | Apply Noctalia QML patches |
| **10** | Finalization | Udev rules, lingering, cache updates |

---

## What Gets Installed

### Desktop Core
- **Niri** - Scrollable-tiling Wayland compositor
- **Noctalia Shell** - Quickshell-based desktop shell/panel
- **WezTerm** - GPU-accelerated terminal emulator
- **Walker** - Application launcher
- **Rofi** - Application launcher (alternative)

### File Management
- **Yazi** - Terminal file manager with plugins
- **Nautilus** - GNOME file manager

### Theming
- Catppuccin Mocha color scheme
- Papirus-Dark icon theme
- JetBrainsMono Nerd Font
- Kvantum Qt theme engine
- Vimix cursors

### Shell
- Zsh with Oh My Zsh (kphoen theme)
- Eza (modern ls replacement)
- Fastfetch (system fetch)
- Custom aliases and environment variables

### System Services
- PipeWire (audio + Bluetooth)
- NetworkManager
- CUPS (printing)
- greetd (auto-login to Niri)
- Bluetooth with auto-reconnect

### Development Tools
- Node.js, Rust/Cargo, Python 3
- Git, Neovim (from mynvim flake)
- Docker, build-essential

---

## Remaining Manual Steps

After running the installer, the following still needs manual work:

### 1. Noctalia Shell Build
Noctalia and Quickshell must be built from source:

```bash
# Build Quickshell
git clone https://git.outfoxxed.me/quickshell/quickshell.git
cd quickshell
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build
sudo cmake --install build

# Build Noctalia Shell
git clone https://github.com/noctalia-dev/noctalia-shell.git
cd noctalia-shell
mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
cmake --build .
sudo cmake --install .
```

### 2. Neovim from mynvim
```bash
git clone https://github.com/viitorags/nvim ~/.config/nvim
nvim --headless "+Lazy! sync" +qa
```

### 3. Niri Session File
Create `/usr/share/wayland-sessions/niri.desktop`:
```ini
[Desktop Entry]
Name=Niri
Comment=Niri compositor
Exec=niri-session
Type=Application
```

### 4. Claude Code (Optional)
```bash
npm install -g @anthropic-ai/claude-code
```

### 5. Catppuccin GTK Theme
```bash
git clone https://github.com/catppuccin/gtk.git /tmp/catppuccin-gtk
cd /tmp/catppuccin-gtk
./install.sh -m mocha -a lavender
```

---

## What Cannot Be Replicated

| Feature | Reason | Closest Equivalent |
|---------|--------|-------------------|
| **NixOS module system** | Nix-specific design pattern | Debian packaging + systemd |
| **Home Manager** | Nix-specific user env manager | Manual dotfiles + systemd user services |
| **Stylix** | Nix-specific theming framework | Manual GTK/Qt/Kvantum/terminal configs |
| **Nix flake pinning** | Nix-specific dependency pinning | apt pinning + manual version control |
| **NixOS OZONE_WL=1** | NixOS-specific env var | Handled by Wayland session detection |
| **Nix shell environments** | Nix-specific dev shells | pyenv, nvm, asdf, or manual installs |
| **Nix package overlays** | Nix-specific overlay system | Manual patching of .deb packages |
| **noctalia-shell-patched (wrapper)** | References Nix store paths | Replaced by direct quickshell invocation |
| **Immutability/atomic upgrades** | NixOS unique feature | Not replicated |
| **/nix/store paths** | NixOS store semantics | Regular FHS paths |

---

## Backup and Rollback

### Backup
The installer automatically creates a backup before making changes:
```bash
# Created at: /tmp/nixdots-migration-backup-<timestamp>/
```

Or you can create one manually:
```bash
python3 installer/install.py --backup
```

### Rollback
To restore from a backup:
```bash
# Copy backed up configs back
cp -r /tmp/nixdots-migration-backup-<timestamp>/.config ~/
cp /tmp/nixdots-migration-backup-<timestamp>/.zshrc ~/

# Rollback packages (view what was installed first)
grep "Installing" /tmp/nixdots-install-<timestamp>.log

# Remove source-built packages
cargo uninstall niri yazi-fm yazi-cli elkowar-eww

# Remove user
sudo userdel -r kotlin
```

---

## Validation Checklist

After installation, verify:

- [ ] `niri` launches (from TTY: `niri-session`)
- [ ] Noctalia shell appears (bar, panels, launcher)
- [ ] Mod+Return opens WezTerm
- [ ] Mod+A opens Walker
- [ ] Mod+F toggles Noctalia launcher
- [ ] Workspace switching with Mod+1..9
- [ ] Media keys work (XF86Audio*)
- [ ] Bluetooth connects to managed devices
- [ ] PipeWire audio works
- [ ] NetworkManager connects to networks
- [ ] Rofi launches with Mod+Space (or walker)
- [ ] GTK apps use Catppuccin theme
- [ ] Qt apps use Kvantum theme
- [ ] Wallpapers are loaded by Noctalia
- [ ] Patched QML files are active
- [ ] Noctalia plugins are loaded (mpris, workspace overview, etc.)

---

## Architecture Migration Map

```
NixOS Concept              → Debian Equivalent
─────────────────────────────────────────────────────
flake.nix                  → installer/install.py + apt
nixpkgs                    → Debian repos
nixos-rebuild              → apt install + manual steps
home-manager               → dotfiles + systemd --user
systemd services (NixOS)   → systemd services (Debian)
stylix                     → manual GTK/Qt/Kvantum configs
niri-flake                 → cargo install niri
noctalia (flake input)     → git clone + cmake build
quickshell (flake input)   → git clone + cmake build
xdg-desktop-portal-wlr     → patched .portal file
greetd + tuigreet          → greetd (or lightdm)
environment.systemPackages → apt packages
home.packages              → apt + cargo + flatpak
xdg.configFile             → ~/.config/ symlinks
systemd.user.services      → ~/.config/systemd/user/
fonts.packages             → apt font packages
boot.kernel.sysctl         → /etc/sysctl.d/
networking.*               → NetworkManager config
services.pipewire          → pipewire + wireplumber pkgs
virtualisation.libvirtd    → libvirt-daemon-system
hardware.bluetooth         → bluez + blueman
```

---

## License

This migration project follows the same license as the original Nixdots repository.
