# Nixdots Repository Audit Report

## Repository Overview

**Repository:** https://github.com/Redm00use/Nixdots  
**Base:** NixOS 26.05 + Home Manager 26.05  
**Active Host:** `kotlin` (x86_64-linux, AMD GPU, desktop role)  
**Desktop Stack:** Niri WM + Noctalia Shell (Quickshell-based)

---

## 1. Top-Level Directory Structure

| Directory | Purpose | Migration Status |
|-----------|---------|-----------------|
| `flake.nix` | Main flake entry point | Not portable - replaced by Debian packaging |
| `lib/` | Shared builders: mkHost.nix, mkHome.nix, theme.nix | Architecture reference |
| `modules/nixos/` | System-level NixOS modules | Translated to Debian services |
| `modules/home-manager/` | User-level Home Manager modules | Translated to dotfiles/systemd user services |
| `hosts/` | Machine-specific configs (kotlin, gh0stk, slime) | `kotlin` configs extracted |
| `config/` | Static config files for niri, rofi, walker, yazi, noctalia | Direct copy |
| `patches/` | Source patches (noctalia QML, stylix kmscon) | Preserved and documented |
| `vendor/` | Vendored Noctalia plugins (6 plugins) | Direct copy |
| `pkgs/` | Local package definitions (cider, sunder, chrome-canary, portproton, php-cs-fixer) | Source builds or Debian alternatives |
| `assets/` | Wallpapers (60+), profile.png, previews | Direct copy |
| `dev/` | Dev shells, claude packages, nvim integration | Optional; dev shells translated to asdf/pyenv |
| `profiles/` | Referenced in AGENTS.md but not present as directory | N/A |
| `libraries/` | Java libraries for Minecraft server | N/A - server-specific |

---

## 2. System Packages (environment.systemPackages)

### Core System Packages
| Nix Package | Debian Equivalent | Status |
|-------------|------------------|--------|
| git | git | ✅ Direct |
| wget | wget | ✅ Direct |
| unzip, zip, unrar | unzip, zip, unrar-free | ✅ Direct |
| ffmpeg | ffmpeg | ✅ Direct |
| tree | tree | ✅ Direct |
| brightnessctl | brightnessctl | ✅ Direct |
| playerctl | playerctl | ✅ Direct |
| zsh | zsh | ✅ Direct |
| eza | eza | ✅ Direct |
| pamixer | pamixer | ✅ Direct |
| pavucontrol | pavucontrol | ✅ Direct |
| grim | grim | ✅ Direct |
| slurp | slurp | ✅ Direct |
| wl-clipboard | wl-clipboard | ✅ Direct |
| wtype | wtype | ✅ Direct |
| cliphist | cliphist | ✅ Direct |
| xwayland-satellite | xwayland-satellite | ✅ Direct |
| freerdp | freerdp2-x11 | ✅ Direct (name diff) |
| exfatprogs | exfatprogs | ✅ Direct |
| upower | upower | ✅ Direct |
| gparted | gparted | ✅ Direct |
| mpv | mpv | ✅ Direct |
| yt-dlp | yt-dlp | ✅ Direct |
| telegram-desktop | telegram-desktop | ✅ Direct |
| ark | ark | ✅ Direct |
| adwaita-icon-theme | adwaita-icon-theme | ✅ Direct |
| hicolor-icon-theme | hicolor-icon-theme | ✅ Direct |
| pfetch-rs | ❌ Not in Debian repos | ⚠️ Source build |
| eww | ❌ Not in Debian repos | ⚠️ Source build (cargo) |
| qemu | qemu-system-x86 | ✅ Direct |
| avahi | avahi-daemon | ✅ Direct |
| font-awesome | fonts-font-awesome | ✅ Direct (name diff) |
| nerd-fonts.jetbrains-mono | fonts-jetbrains-mono | ⚠️ Nerd font variant may differ |
| noto-fonts | fonts-noto | ✅ Direct |
| noto-fonts-color-emoji | fonts-noto-color-emoji | ✅ Direct |
| qtstyleplugins | qt5-style-plugins | ⚠️ May differ |
| qt5ct | qt5ct | ✅ Direct |
| qt6ct | qt6ct | ✅ Direct |
| qtmultimedia | qt6-multimedia | ✅ Direct |
| kvantum | qt6-style-kvantum | ✅ Direct |

### Desktop-Only System Packages
| Nix Package | Debian Equivalent | Status |
|-------------|------------------|--------|
| libreoffice-fresh | libreoffice | ✅ Direct |
| obsidian | obsidian | ✅ Direct |
| google-chrome-canary | ❌ Not in Debian | ⚠️ .deb install |
| cowsay | cowsay | ✅ Direct |
| cmatrix | cmatrix | ✅ Direct |
| nbfc-linux | ❌ Not in Debian | ⚠️ Source build |

---

## 3. System Services

| NixOS Module | Debian Equivalent | Status |
|-------------|------------------|--------|
| greetd + tuigreet | greetd (from greetd package) | ⚠️ May not be in stable; alternative: lightdm/auto-login tty |
| niri (niri-flake) | Source build from cargo/git | ⚠️ Not in Debian repos |
| pipewire | pipewire, wireplumber, pipewire-pulse | ✅ Direct |
| bluetooth (bluez) | bluez, bluez-utils | ✅ Direct |
| blueman | blueman | ✅ Direct |
| NetworkManager | network-manager | ✅ Direct |
| cups + printer drivers | cups, cups-filters, printer-driver-* | ✅ Direct |
| accounts-daemon | accountsservice | ✅ Direct |
| polkit + gnome-keyring | policykit-1, gnome-keyring | ✅ Direct |
| udisks2 | udisks2 | ✅ Direct |
| devmon | udisks2 (built-in auto-mount) | ✅ Direct |
| thermald | thermald | ✅ Direct |
| zram | zramswap/zram-tools | ✅ Direct |
| flatpak | flatpak | ✅ Direct |
| steam | steam | ✅ Direct |
| gamemode | gamemode | ✅ Direct |
| libvirtd | libvirt-daemon-system | ✅ Direct |
| virt-manager | virt-manager | ✅ Direct |
| cloudflare-warp | ❌ Not in Debian | ⚠️ Manual install |
| anydesk | ❌ Not in Debian | ⚠️ .deb from anydesk.com |
| opentabletdriver | ❌ Not in Debian | ⚠️ Manual install |
| xdg-desktop-portal | xdg-desktop-portal | ✅ Direct |
| xdg-desktop-portal-gtk | xdg-desktop-portal-gtk | ✅ Direct |
| xdg-desktop-portal-wlr | xdg-desktop-portal-wlr | ✅ Direct |

---

## 4. User Packages (Home Manager)

| Nix Package | Debian Equivalent | Status |
|-------------|------------------|--------|
| gnome.gvfs | gvfs, gvfs-backends | ✅ Direct |
| nautilus | nautilus | ✅ Direct |
| bc | bc | ✅ Direct |
| imagemagick | imagemagick | ✅ Direct |
| imv | imv | ✅ Direct |
| qimgv | qimgv | ✅ Direct |
| usbutils | usbutils | ✅ Direct |
| gpu-screen-recorder | ❌ Not in Debian | ⚠️ Source build |
| vesktop | ❌ Not in Debian | ⚠️ .deb from GitHub |
| gowall | ❌ Not in Debian | ⚠️ Source build |
| system-config-printer | system-config-printer | ✅ Direct |
| pokemon-colorscripts | ❌ Not in Debian | ⚠️ Source build |
| android-tools | android-tools-adb, android-tools-fastboot | ✅ Direct (name diff) |
| obs-studio | obs-studio | ✅ Direct |
| obsidian | obsidian | ✅ Direct |
| qbittorrent | qbittorrent | ✅ Direct |

---

## 5. Home Manager Programs

| Program | Description | Migration |
|---------|-------------|-----------|
| niri | Niri WM config (config.kdl) | ✅ Direct copy |
| rofi | Rofi + plugins (calc, emoji, file-browser) | ✅ Debian if available; cargo install |
| walker | Walker launcher | ⚠️ Source build (Go) |
| stylix | Theming framework (GTK/Qt/Cava) | Replaced by manual configs |
| noctalia | Noctalia shell patches + settings | ✅ Config preserved |
| wezterm | Terminal emulator | ⚠️ .deb from GitHub |
| direnv | Environment loader | ✅ apt direnv |
| yazi | Terminal file manager | ⚠️ cargo install |
| btop | System monitor | ✅ apt btop |
| shell | Zsh + oh-my-zsh | ✅ oh-my-zsh from GitHub |
| fastfetch | System fetch tool | ⚠️ Source build |
| cava | Audio visualizer | ✅ apt cava |
| lazygit | Git TUI | ⚠️ Source build |
| cider | Apple Music client | ⚠️ .deb from cider.sh |
| discord | Discord client | ⚠️ vesktop from GitHub |
| mailspring | Email client | ⚠️ .deb from GitHub |
| zed | Zed editor | ⚠️ .deb from zed.dev |
| qbittorrent | Torrent client | ✅ Direct |
| sioyek | PDF viewer | ⚠️ Source build |

---

## 6. Patches

### patches/noctalia/ (6 QML patch files)

| File | What It Patches | Why | Migration |
|------|----------------|-----|-----------|
| AllBackgrounds.qml | Noctalia background rendering | Unified shadow system, separate bar/panel opacity | ✅ Preserved in vendor tree |
| Bar.qml | Noctalia bar component | Hot corner, filtered widgets, auto-hide + panel integration | ✅ Preserved |
| BarContentWindow.qml | Noctalia bar content window | Auto-hide timers, hover detection, layer management | ✅ Preserved |
| LauncherCore.qml | Noctalia launcher | Rofi-style colors, icon resolution | ✅ Preserved |
| MainScreen.qml | Noctalia main screen | Single PanelWindow per screen management | ✅ Preserved |
| ThemeIcons.qml | Noctalia icon resolution | Load icons from absolute paths (not just theme names) | ✅ Preserved |

### patches/stylix/ (1 patch)

| File | What It Patches | Migration |
|------|----------------|-----------|
| kmscon-extraConfig.patch | Stylix kmscon module compat for nixpkgs 26.05 | ❌ Not needed on Debian (kmscon may not be used) |

---

## 7. Vendored Plugins

### vendor/noctalia/plugins/ (6 plugins)

| Plugin | Description | Type | Migration |
|--------|-------------|------|-----------|
| assistant-panel | AI assistant + translator panel | Full QML plugin | ✅ Direct copy |
| calibre-provider | Calibre e-book integration | Simple provider | ✅ Direct copy |
| mpris-lyric | MPRIS lyrics display | Bar widget + settings | ✅ Direct copy |
| niri-overview-launcher | Niri workspace overview | Launcher plugin | ✅ Direct copy |
| screen-recorder | Screen recording + GIF maker | Full plugin | ✅ Direct copy |
| workspace-overview | Workspace grid overview | Bar widget | ✅ Direct copy |

---

## 8. Local Packages

| Package | Source | Debian Available? | Migration |
|---------|--------|-------------------|-----------|
| cider (cider.sh) | Arch Linux .pkg.tar.xz | ❌ | ⚠️ Direct download or cargo build |
| sunder (YouTube music) | GitHub Rust/Tauri project | ❌ | ⚠️ Source build with cargo |
| google-chrome-canary | .deb from dl.google.com | ❌ | ✅ .deb install |
| portproton | GitHub | ❌ | ⚠️ Flatpak from flathub |
| php-cs-fixer | .phar from GitHub | ❌ | ⚠️ Manual install (dev tool) |

---

## 9. Environment Variables

| Variable | Value | Migration |
|----------|-------|-----------|
| TERMINAL | wezterm | ✅ In .zshrc + environment.d |
| EDITOR | nvim | ✅ In .zshrc |
| QT_QPA_PLATFORM | wayland;xcb | ✅ In .zshrc |
| NIXOS_OZONE_WL | 1 | ⚠️ Changed to XDG_CURRENT_DESKTOP=niri |
| XKB_DEFAULT_OPTIONS | led:scroll | ✅ In .zshrc |
| XDG_ICON_THEME | Papirus-Dark | ✅ In .zshrc |
| ICON_THEME | Papirus-Dark | ✅ In .zshrc |
| QS_ICON_THEME | Papirus-Dark | ✅ In niri config |

---

## 10. Shell Aliases

| Alias | Command | Migration |
|-------|---------|-----------|
| rb | nixos-rebuild switch | ⚠️ Kept for reference but N/A on Debian |
| upd | nix flake update | ⚠️ Kept for reference |
| upg | nixos-rebuild switch --upgrade | ⚠️ Kept for reference |
| conf | nvim configuration.nix | ⚠️ Kept for reference |
| pkgs | nvim packages.nix | ⚠️ Kept for reference |
| ls | eza -ha --icons=auto... | ✅ Preserved |
| ll | eza -lh --icons=auto | ✅ Preserved |
| ff | fastfetch | ✅ Preserved |
| clear | clear + printf | ✅ Preserved |
| c | claude | ✅ Preserved (if installed) |

---

## 11. Niri Keybindings

**Migration: 1:1 preserved in config.kdl**

All keybindings are stored in `configs/niri/config.kdl` and will be directly copied.

| Category | Count | Migration |
|----------|-------|-----------|
| Application launches | ~12 | ✅ |
| Workspace switching | ~18 | ✅ |
| Window management | ~30 | ✅ |
| Column management | ~20 | ✅ |
| Monitor management | ~10 | ✅ |
| Media keys | ~7 | ✅ |
| Window rules | ~35 | ✅ |

---

## 12. Niri Window Rules

Total: 35+ window rules for specific apps including:
- Floating rules (pavucontrol, dialogs, portals, etc.)
- Size rules (Telegram, Chrome, etc.)
- Opacity rules
- Screencast blocking (Telegram)
- Corner radius / shadow rules

**Migration: 1:1**

---

## 13. Risks and Gaps

### High Risk
1. **Noctalia Shell** - Requires Quickshell, which is not in Debian repos. Must be built from source. Noctalia itself requires building from source pinned to specific commit.
2. **Niri** - Not in Debian stable. Must be built from cargo or installed from experimental.
3. **Quickshell** - Not in Debian repos at all. Requires building from custom git repo.

### Medium Risk
4. **Stylix theming** - Stylix is a Nix-specific framework. Must be replaced with manual GTK/Qt/Kvantum configs.
5. **xdg-desktop-portal-wlr** - On Debian, portal-wlr needs manual `UseIn=niri` patch.
6. **greetd auto-login** - May not be packaged in Debian stable; alternatives needed.
7. **Niri session** - Debian needs a custom `/usr/share/wayland-sessions/niri.desktop` for display manager support.

### Lower Risk
8. **Nix aliases** - `rb`, `upd`, `upg` aliases won't work without Nix installed.
9. **catppuccin-userstyles** - Requires Chrome/Stylus extension.
10. **Claude/DeepSeek** - Requires npm install of claude-code.
11. **Vimix-cursors** - Not in Debian repos; needs manual install from GitHub.
