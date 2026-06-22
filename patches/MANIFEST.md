# Patch Manifest

This directory contains patches from the original Nixdots repository that modify
upstream Noctalia Shell source files. Each patch is preserved in the Debian
migration and applied by the installer.

---

## 1. Noctalia Patches

### Directory: `patches/noctalia/`

These QML files replace files in the Noctalia Shell source tree when launched
via `quickshell --path <patched_config>`.

| Patch File | Upstream File | Purpose | Can Be Replaced By Config? |
|-----------|---------------|---------|---------------------------|
| `AllBackgrounds.qml` | `Modules/MainScreen/Backgrounds/AllBackgrounds.qml` | Unified shadow system for bar + panel backgrounds. Separate opacity for bar and panels. | No - code change |
| `Bar.qml` | `Modules/Bar/Bar.qml` | Hot corner trigger on first widget section. Filtered widget registry validation. | No - code change |
| `BarContentWindow.qml` | `Modules/MainScreen/BarContentWindow.qml` | Auto-hide timer improvements, hover detection, content unloading on hide. Panel open detection. | No - code change |
| `LauncherCore.qml` | `Modules/Panels/Launcher/LauncherCore.qml` | Rofi color scheme constants. Custom icon resolution for .desktop files with absolute icon paths. | Partially - theme colors could be config |
| `MainScreen.qml` | `Modules/MainScreen/MainScreen.qml` | Main screen PanelWindow manager. Manages all panels, bar, dock, and OSD per screen. | No - core architecture |
| `ThemeIcons.qml` | `Commons/ThemeIcons.qml` | Icon lookup: accept both theme icon names AND absolute file paths. Override/substitution map for tricky app icons (google-chrome-canary, pavucontrol, etc.). | No - required for icon correctness |

### How Patches Are Applied

The patches are applied by the `noctalia-shell-patched` wrapper in the original
NixOS setup. The wrapper:
1. Takes the Noctalia source tree from the pinned flake input
2. Applies `substituteInPlace` text replacements (LauncherCore color hacks, PluginService auto-update)
3. Copies patched QML files over the originals
4. Launches via `quickshell --path <patched_tree>`

In the Debian migration, the patched files are copied into the user's
`~/.config/noctalia/` directory as part of the installer. The Noctalia runtime
will load these files instead of the bundled defaults when pointed at the config
directory.

---

## 2. Stylix Patch

### Directory: `patches/stylix/`

| Patch File | Purpose | Needed on Debian? |
|-----------|---------|-------------------|
| `kmscon-extraConfig.patch` | Compatibility patch for Stylix kmscon module on nixpkgs 26.05 (deprecated `services.kmscon.config` → `extraConfig`) | **No** - Stylix is not used on Debian. KMS console theming is not replicated. |

---

## Patch Application Verification

To verify patches are active:

1. **ThemeIcons patch**: Check that apps with absolute Icon= paths in .desktop files
   render correctly (e.g., game icons, custom app icons).

2. **Bar patches**: Check auto-hide behavior, hot corner activation, and
   bar/panel background opacity.

3. **LauncherCore patch**: Check that the launcher uses Rofi-style colors
   instead of the default Noctalia launcher colors.

4. **AllBackgrounds patch**: Check that bar and panel backgrounds use
   the unified shadow system with correct opacity.
