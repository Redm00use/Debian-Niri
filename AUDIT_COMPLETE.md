# Complete Project Audit: Nixdots → Debian

**Project A (source of truth):** `/home/kotlin/nixdots/` — NixOS configuration  
**Project B (migration):** `/home/kotlin/Debian/` — Debian port  
**Date:** 2026-06-22  
**Auditor:** Automated verification agent

---

## Migration Coverage

| Category | Fully | Partial | Missing |
|----------|-------|---------|---------|
| System Packages | 80% | 15% | 5% |
| System Services | 45% | 35% | 20% |
| User Packages | 60% | 20% | 20% |
| User Configs | 50% | 35% | 15% |
| Desktop/DE | 25% | 50% | 25% |
| Theming | 60% | 30% | 10% |
| Startup Flow | 20% | 30% | 50% |
| Patches | 100% | 0% | 0% |
| Vendor Assets | 100% | 0% | 0% |
| Shell/CLI | 85% | 10% | 5% |
| **Overall** | **~60%** | **~25%** | **~15%** |

---

## Critical Problems

These issues would prevent the Debian system from behaving like the NixOS system at all.

### C1. Niri `spawn-at-startup` has Nix store path — BROKEN

**File:** `configs/niri/config.kdl`, line 105

```
spawn-at-startup "/nix/store/gp0908pxmyc5w8y5hrl6mbjrphc0idkw-polkit-gnome-0.105/bin/polkit-gnome-authentication-agent-1"
```

The path is a Nix store hash that does not exist on Debian. This `spawn-at-startup` command will fail on every Niri launch. The polkit authentication agent will not start, meaning GUI password prompts (for admin tasks, package installs, etc.) will not work.

**Fix needed:** Replace with `"polkit-gnome-authentication-agent-1"` or use the session script approach.

---

### C2. `system/` files NEVER deployed by installer

**Files affected:**
- `system/niri-session` — Custom session launcher script
- `system/niri-session.desktop` — Wayland session entry for display managers
- `system/noctalia-shell.service` — systemd user service for Noctalia

The installer defines `SYSTEM_SRC = PROJECT_ROOT / "system"` at line 44 but **never uses it**. None of these files are copied to the target system.

**Impact:**
- `greetd` is configured to run `niri-session` (line 748) but this binary does not exist on the target → **login fails entirely**
- No Wayland session entry for display managers
- No systemd user service for Noctalia shell

---

### C3. greetd configured with missing binary — LOGIN FAILURE

**File:** `installer/install.py`, lines 743–749

```python
greetd_config.write_text(f"""[terminal]
vt = 1

[default_session]
command = "niri-session"
user = "{USERNAME}"
""")
```

`niri-session` is a custom script from `system/niri-session` that is NOT deployed (see C2). greetd will fail because the command does not exist in PATH. The system will boot to a black screen or login failure.

---

### C4. No Noctalia `settings.json` generated

The original `modules/home-manager/programs/noctalia/default.nix` produces a complete Noctalia configuration with ~600 lines of settings covering:

- **Bar**: position, layout, widgets (taskbar, workspace, tray, clock, volume, bluetooth, keyboard layout, custom buttons with RDP integration)
- **Launcher**: icon mode, clipboard history, search categories, view mode
- **Audio**: visualizer type, volume step, MPRIS blacklist
- **Notifications**: opacity, duration, sound, battery toast, keyboard layout toast
- **OSD**: position, auto-hide, enabled types
- **Wallpaper**: directory, fill mode, transition, Wallhaven integration
- **Dock**: animation, auto-hide, pinned apps
- **Control Center**: cards, shortcuts, disk path
- **Session Menu**: power options, countdown, keybinds
- **Lock Screen**: blur, tint, media controls
- **Idle**: screen off, suspend, lock timeouts
- **Desktop Widgets**: clock, weather, system stats, media player
- **Color schemes**: Catppuccin, dark mode

**The Debian installer only creates `plugins.json` and `todo-plugin-settings.json`.** Without `settings.json`, Noctalia uses all defaults which produce a completely different bar layout, widget set, and behavior than the NixOS setup.

**Fix needed:** Generate `~/.config/noctalia/settings.json` with the full configuration from the original.

---

### C5. Vimix cursors — download URL is 404

**File:** `installer/install.py`, line 1567

```python
vimix_url = "https://github.com/vinceliuice/Vimix-cursors/releases/download/v1.0/Vimix-cursors.tar.xz"
```

This URL returns HTTP 404. The Vimix-cursors repository does not have this release artifact. The cursor theme installation fails silently (wrapped in try/except). GTK/Qt configuration references `Vimix-cursors` as the cursor theme, but the icons never get installed, so the cursor will fall back to the default Debian cursor.

---

## Major Problems

### M1. SSH_AUTH_SOCK hardcoded UID 1000

**File:** `configs/niri/config.kdl`, line 98

```
"SSH_AUTH_SOCK" "/run/user/1000/keyring/ssh"
```

Hardcoded UID 1000. If the `kotlin` user gets a different UID on a fresh Debian install (e.g., first user UID 1000 is typical but not guaranteed), the SSH agent socket will not work. The original NixOS setup guarantees UID 1000 because it's the first user. The `niri-session` script uses `${XDG_RUNTIME_DIR}/keyring/ssh` which is dynamic and correct, but that script is not deployed (C2).

**Impact:** SSH key forwarding and git operations over SSH will fail.

---

### M2. spotify-catppuccin desktop entry missing

**File:** `configs/niri/config.kdl`, line 125

```
Mod+S { spawn "gtk-launch" "spotify-catppuccin"; }
```

There is no `spotify-catppuccin.desktop` entry anywhere in the migration. The keybinding references a non-existent launcher entry. Pressing Mod+S will silently do nothing.

**In NixOS**, this worked if a Spotify Catppuccin wrapper was available (from `catppuccin-spotify` or similar). No equivalent exists in the Debian migration.

---

### M3. Noctalia shell started from 3 sources — duplicate processes

The migration creates three mechanisms that attempt to start Noctalia:

1. **`niri-session` script** (if deployed): starts `noctalia-shell-patched &` as background process
2. **`noctalia-shell.service`** (if deployed): systemd user service for noctalia
3. **Niri keybindings**: `Mod+F` calls `noctalia-shell-patched ipc call launcher toggle`

In the original NixOS, only ONE instance is started (via the systemd user service). The Debian migration risks having two instances running simultaneously, competing for the same Wayland socket and resources.

---

### M4. greetd configuration differs from NixOS — no greeter UI

**NixOS original** (greetd.nix):
```nix
default_session = {
  command = "${pkgs.tuigreet}/bin/tuigreet --time --remember --cmd niri-session";
  user = "greeter";
};
initial_session = {
  command = "niri-session";
  user = "kotlin";
};
```

**Debian migration**:
```python
[default_session]
command = "niri-session"
user = "kotlin"
```

Differences:
- No tuigreet TUI greeter (no user selection, no password prompt)
- No `initial_session` separate from `default_session`
- User logs in as `kotlin` automatically without any authentication
- Even if it worked, the security model is different

---

### M5. No Noctalia plugin settings

The original generates settings for:
- `noctalia/plugins/mpris-lyric/settings.json` — player name, update interval, width, hide when inactive
- `noctalia/plugins/assistant-panel/settings.json` — AI provider config (DeepSeek URL, API key, model), translator backend, panel position/size

The Debian installer generates `settings.json` only for the todo plugin. The mpris-lyric and assistant-panel plugins will use defaults, which means:
- MPRIS lyric display may be inactive or wrong
- Assistant panel won't have the DeepSeek AI configuration

---

### M6. No LACT daemon service or fan curve config

The original `fan-control.nix` creates:
- `/etc/lact/config.yaml` with GPU-specific fan curve (30°→20%, 50°→30%, ... 90°→100%)
- `lact.service` systemd daemon
- `amdgpu.ppfeaturemask=0xfffd7fff` kernel parameter

The Debian installer (lines 1642–1658) handles:
- Installing the `lact` package ✅
- Adding the kernel parameter to GRUB ✅ (may fail if GRUB config format differs)

But MISSING:
- LACT daemon systemd service (needed for automatic fan control)
- `/etc/lact/config.yaml` with fan curve (without it, fan control stays disabled)
- The specific GPU PCI ID (1002:67DF-1DA2:E366-0000:04:00.0) from the original config

---

### M7. Neovim not installed

The `EDITOR=nvim` environment variable is set in:
- `.zshrc` 
- `environment.d/nixdots.conf`

But `neovim` (or `nvim`) is NOT in any package list. The `mynvim` flake from the original is documented as a manual setup step, but the EDITOR env var suggests nvim should be available immediately. First use of `$EDITOR` will fail.

---

### M8. No gamescope or Steam gamescope session

Original NixOS:
```nix
programs.steam.gamescopeSession.enable = true;
programs.gamescope.enable = true;
```

Debian installer: Nothing. `gamescope` is not in any package list.

---

### M9. Noctalia-shell-patched script path breaking

**File:** `scripts/noctalia-shell-patched.sh`

The script determines patch paths relative to itself:
```bash
PATCH_DIR="$(dirname "$0")/../patches/noctalia"
```

But the script is intended to be deployed to `~/.local/bin/noctalia-shell-patched`. When run from there, `$(dirname "$0")` resolves to `~/.local/bin/`, so `../patches/noctalia` becomes `~/.local/patches/noctalia` which does NOT exist.

**Fix needed:** Either make the script self-contained, or deploy it in a way that preserves the path relationship to the project files.

---

### M10. Yazi plugins not configured

The original Yazi config wires up 8 plugins:
- `diff`, `full-border`, `git`, `mount`, `ouch`, `rich-preview`, `yatline` (from nixpkgs)
- `kdeconnect-send` (local plugin at `./plugins/kdeconnect-send.yazi`)

The Debian installer copies `init.lua` which references these plugins via `require("full-border"):setup()`, `require("git"):setup()`, etc., but the plugin binaries and packages are never installed. Yazi will start but fail to load the plugins.

---

## Minor Problems

### m1. `pokemon-colorscripts` not in Debian repos

The `DESKTOP_PACKAGES` dict maps `"pokemon-colorscripts"` to `"pokemon-colorscripts"` but this is an AUR package, not in Debian repositories. The apt install will fail.

### m2. LACT package may not exist in Debian stable

`lact` (Linux GPU fan control) is not available in Debian stable. It may require building from source or using a third-party repository.

### m3. `protonup-qt` not in Debian repos

`protonup-qt` is mapped in `SYSTEM_PACKAGES` but is not available in Debian stable repositories.

### m4. GTK bookmarks file overwrites per-item

The GTK bookmarks file is created with:
```python
for bm in ["Documents", "Downloads", ...]:
    gtk3_bookmarks.write_text(f"file://{USER_HOME}/{bm}\n")
```

The loop uses `write_text` (not append) so only the LAST bookmark (`nixdots`) is written. All other bookmarks are overwritten.

### m5. Hardcoded DeepSeek API key references in comments

The environment files contain referenced DeepSeek API key values in comments. While not functional, the secrets should be removed from the repository and set via environment variables only.

### m6. Noctalia `colors.nix` file not converted

The original `config/noctalia/colors.nix` defines a Catppuccin Mocha color scheme for Noctalia. On NixOS this is evaluated at build time and injected into settings. On Debian this file is never converted to a runtime format.

### m7. `usbredir` package missing

The original `home.nix` includes `usbredir` (USB redirection for SPICE/VMs). Not in Debian package lists.

### m8. `spiceUSBRedirection` not enabled

Original `virt-manager.nix` has `virtualisation.spiceUSBRedirection.enable = true`. Not configured in Debian migration.

### m9. `kdeconnect` not installed

Yazi keybinding `<C-s>` runs `plugin kdeconnect-send`, but KDE Connect is not part of the package list.

### m10. `gamemode` already in `SYSTEM_PACKAGES` AND `DESKTOP_PACKAGES`

`gamemode` is listed in both dictionaries (line 302 and line 392), causing a duplicate apt install attempt.

---

## Missing Components

### Components present in Nixdots but absent from Debian

| Component | Type | Impact |
|-----------|------|--------|
| `niri-session` script (from `system/`) | Session launcher | **Critical** — login fails |
| `noctalia-shell.service` (from `system/`) | Systemd user service | **Critical** — Noctalia not started |
| `niri-session.desktop` | Wayland session entry | **Major** — DM integration |
| `settings.json` for Noctalia | User config | **Critical** — different UI |
| Plugin settings (mpris-lyric, assistant-panel) | User config | **Major** — wrong defaults |
| `colors.nix` → Noctalia colors | Theme data | **Minor** — theme mismatch |
| `gamescope` | Package | **Medium** — no gamescope session |
| `LACT` daemon service + config | System service | **Medium** — no fan curve |
| `usbredir` | Package | **Low** — USB forwarding |
| `neovim` | Package | **Medium** — $EDITOR fails |
| `kdeconnect` | Package | **Low** — Yazi plugin |
| Yazi plugins (8 total) | User config | **Medium** — Yazi features missing |
| `spotify-catppuccin` desktop entry | Desktop entry | **Low** — keybinding silent |
| `fcitx5` or `ibus` (Japanese/Chinese input) | IME | **Low** — not in original but keyboard layout may need it |
| Steam `remotePlay`/`dedicatedServer` firewall | Firewall | **Low** — steam remote play may not work |

---

## Architecture Differences

| Aspect | Nixdots (NixOS) | Debian (Migration) | Assessment |
|--------|-----------------|-------------------|------------|
| **Package management** | `nixpkgs`, flakes, overlays | `apt`, cargo, manual .deb | Expected difference |
| **Module system** | NixOS + Home Manager `imports` | Imperative Python stages | Pragmatic but less composable |
| **Service management** | NixOS `systemd.services.*` | Direct systemd enable | ✅ Equivalent |
| **User config** | Home Manager `xdg.configFile` | Direct file copies | ✅ Equivalent |
| **Startup flow** | greetd → tuigreet → niri-session → systemd user services | greetd → niri-session (broken) | ❌ Broken |
| **Noctalia config** | Nix-derived JSON at build time | No runtime generation | ❌ Missing entirely |
| **Stylix theming** | Dynamic base16 theme system | Hardcoded configs | ⚠️ Acceptable for single theme |
| **Dev shells** | `nix develop` with full toolchain | Manual apt installs | ⚠️ Acceptable difference |
| **Host separation** | `hosts/kotlin`, `hosts/gh0stk`, `hosts/slime` | Single target `kotlin` | ✅ Acceptable for migration |
| **Profile layering** | `suites/base.nix` + `suites/desktop.nix` | `--system-only` vs `--user-only` flags | ⚠️ Less explicit |
| **Patches** | Nix `runCommandLocal` with `substituteInPlace` | Bash script with `sed` + file copies | ✅ Equivalent |
| **Noctalia launch** | Single systemd user service | 3 potential launch paths | ❌ Broken |

---

## Verification Checklist

### System
- ✅ Kernel sysctl (max_map_count, mmap_min_addr, overcommit_memory)
- ✅ NetworkManager + DNS (1.1.1.2, 8.8.8.8)
- ✅ Timezone (Europe/Kyiv)
- ✅ Locale (ru_RU.UTF-8)
- ✅ Console keymap (ru)
- ⚠️ Chrome policies (Catppuccin + Stylus forced install) — NOW FIXED
- ⚠️ AMD GPU env vars (LIBVA_DRIVER_NAME, VDPAU_DRIVER) — NOW FIXED
- ❌ AMD GPU ROCm symlink
- ❌ LACT daemon service + fan curve config
- ❌ gamescope package
- ⚠️ Steam remotePlay/dedicatedServer firewall — PARTIALLY (steam package only)
- ✅ PipeWire audio stack
- ✅ Bluetooth + blueman
- ⚠️ Bluetooth experimental + reconnect service — NOW FIXED
- ✅ CUPS printing
- ✅ NetworkManager
- ✅ Avahi/mDNS
- ✅ UDISKS2
- ❌ greetd tuigreet — replaced with direct login (different UX)
- ❌ greetd niri-session — BROKEN (script not deployed)
- ✅ Polkit + gnome-keyring
- ⚠️ uinput for OpenTabletDriver — NOW FIXED
- ⚠️ Magic Trackpad udev — NOW FIXED
- ✅ ZRAM swap
- ⚠️ Flatpak + WPS Office + PortProton — NOW FIXED (locale overrides added)
- ❌ AnyDesk — not covered
- ❌ Cloudflare WARP — not covered
- ✅ Minecraft server directories — NOW FIXED (partial: no systemd services)
- ❌ Minecraft server systemd unit — not covered
- ❌ Minecraft firewal rule (port 25565) — not covered
- ❌ Cloudflared tunnel service — not covered

### Desktop
- ✅ Niri installed (cargo)
- ⚠️ Niri config.kdl — FIXED: polkit store path is broken
- ❌ Niri session file not deployed
- ❌ Noctalia shell — requires manual build
- ❌ Noctalia settings.json — not generated
- ❌ Noctalia plugin settings — not generated
- ❌ Noctalia colors — not converted
- ⚠️ XDG Desktop Portals — configured but relies on niri-session
- ✅ Clipboard manager (cliphist + wl-paste)
- ✅ Screenshot path configured
- ✅ Screen recording via xdg-desktop-portal-wlr

### User Environment
- ✅ Zsh + Oh My Zsh + kphoen theme
- ✅ Shell aliases (ls, ll, ff, clear, c, rb, upd, etc.)
- ⚠️ Zsh autosuggestions/syntax-highlighting — NOW FIXED
- ✅ Environment variables
- ✅ WezTerm config (most keybindings)
- ❌ WezTerm font rules and zoom toggle
- ⚠️ Yazi config (partial: init.lua copied, no plugins)
- ❌ Neovim — not installed
- ✅ Rofi themes copied
- ⚠️ Rofi extraConfig — NOW FIXED
- ❌ Rofi plugins (calc, emoji, file-browser) — NOW FIXED (in package list)
- ✅ Walker config copied
- ⚠️ Walker + Elephant services — NOW FIXED (user services)
- ✅ Btop config
- ⚠️ Cava config (hardcoded, not dynamic)
- ⚠️ Fastfetch config (logo path fixed)
- ✅ GTK config (Catppuccin, Papirus, Vimix)
- ✅ Qt config (Kvantum)
- ❌ GTK bookmarks — BUG: only last bookmark written
- ✅ Dconf button-layout — NOW FIXED
- ✅ Vimix cursors — URL is 404 ❌
- ✅ WPS skin config — NOW FIXED
- ✅ Flatpak WPS locale overrides — NOW FIXED

### Helper Scripts
- ✅ xfreerdp3 wrapper — NOW FIXED
- ✅ mic_toggle — NOW FIXED
- ✅ scrolllock_keyboard — NOW FIXED
- ✅ catppuccin-userstyles — NOW FIXED
- ✅ Claude wrappers (6 variants) — NOW FIXED
- ✅ Desktop entry cleanup — NOW FIXED

### Packages Status
- ✅ 100+ Debian packages mapped
- ⚠️ gamescope — MISSING
- ⚠️ neovim — MISSING
- ⚠️ usbredir — MISSING
- ⚠️ kdeconnect — MISSING
- ⚠️ pokemon-colorscripts — WRONG (AUR package, not in Debian)
- ⚠️ protonup-qt — may not be in Debian stable
- ⚠️ lact — may not be in Debian stable

### Patches
- ✅ All 6 Noctalia patches preserved in `patches/noctalia/`
- ✅ Patch manifest documents each patch
- ⚠️ Patch application depends on noctalia-shell-patched.sh being deployed correctly

### Vendor Assets
- ✅ All 6 plugins (68 files) in `vendor/noctalia/plugins/`
- ✅ Plugin files copied by installer to `~/.config/noctalia/plugins/`

### Wallpapers
- ✅ All 101 files in `assets/wallpapers/`
- ✅ Copied to `~/Pictures/Wallpapers/`

---

## Recommended Fix Order

| Priority | Issue | Effort | Impact |
|----------|-------|--------|--------|
| **P0** | C2: Deploy `system/` files to target (niri-session, niri.desktop, noctalia.service) | Low | **Login works** |
| **P0** | C1: Fix Niri config.kdl polkit store path | Low | **Polkit agent works** |
| **P0** | C4: Generate Noctalia `settings.json` | High | **Same Noctalia UI** |
| **P1** | C3: Ensure greetd can find niri-session | Low | **Auto-login works** |
| **P1** | C5: Fix Vimix cursor URL or install from Debian package | Low | **Cursor theme works** |
| **P1** | M9: Fix noctalia-shell-patched.sh path resolution | Medium | **Noctalia launches** |
| **P2** | M6: Add LACT daemon systemd service + config | Medium | **GPU fan control** |
| **P2** | M5: Generate plugin settings.json files | Low | **Plugins configured** |
| **P2** | M1: Fix SSH_AUTH_SOCK to use runtime dir | Low | **SSH key auth works** |
| **P2** | M7: Add neovim to package list | Low | **$EDITOR works** |
| **P3** | M10: Install Yazi plugins | Medium | **Yazi features** |
| **P3** | M8: Add gamescope package | Low | **Steam gamescope** |
| **P3** | m4: Fix GTK bookmarks append vs write | Low | **All bookmarks** |
| **P3** | m1: Remove pokemon-colorscripts or find alternative | Low | **Clean install** |
| **P4** | m9: Add kdeconnect package | Low | **File sharing** |
| **P4** | m7: Add usbredir package | Low | **USB forwarding** |
| **P4** | m10: Deduplicate gamemode packages | Low | **Clean install** |

---

## Summary

The migration is **functional in concept but critically incomplete in execution**. The two most severe issues are:

1. **The greetd login flow is broken** because the `niri-session` script is never deployed to the target system. The system will boot to a blank screen.

2. **Noctalia will look and behave completely differently** because its full settings configuration (~600 lines) is never generated.

The installer covers ~60% of the original functionality correctly. The patches, vendor plugins, shell config, theming templates, and package mappings are solid. But the critical startup pathway and the most important user-facing configuration (Noctalia) are not properly handled.

Without fixing P0 and P1 items, the Debian system will not function as a Niri+Noctalia desktop. With those fixes, the migration would be ~85% complete, with the remaining gaps being minor feature differences or items requiring manual build steps (Noctalia source build, Quickshell build, etc.).
