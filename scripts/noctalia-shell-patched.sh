#!/bin/bash
# ── Noctalia Shell (Patched) Launcher ────────────────────────────────────────
#
# This script replicates the behavior of the NixOS noctalia-shell-patched
# wrapper on Debian. It applies Noctalia source patches on-the-fly by copying
# patched QML files into a temporary runtime directory, then launches
# quickshell with that directory as a config path.
#
# The patched directory is cached in /tmp and reused if available.
#
# Usage:
#   noctalia-shell-patched                    # Launch Noctalia shell
#   noctalia-shell-patched ipc call launcher toggle  # IPC commands

set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────
# WARNING: When deployed to ~/.local/bin, set NOCTALIA_PROJECT_ROOT to
# the Debian migration project root, or set NOCTALIA_SOURCE directly.
NOCTALIA_PROJECT_ROOT="${NOCTALIA_PROJECT_ROOT:-}"
QUICKSHELL_BIN="${QUICKSHELL_BIN:-$(command -v quickshell 2>/dev/null || echo /usr/local/bin/quickshell)}"
NOCTALIA_CONFIG_DIR="${HOME}/.config/noctalia"
CACHE_DIR="/tmp/noctalia-shell-patched-${USER}"

# Try to find project root relative to script location
if [ -z "${NOCTALIA_PROJECT_ROOT}" ]; then
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    if [ -f "${SCRIPT_DIR}/../patches/noctalia/Bar.qml" ]; then
        NOCTALIA_PROJECT_ROOT="${SCRIPT_DIR}/.."
    elif [ -f "${SCRIPT_DIR}/../../patches/noctalia/Bar.qml" ]; then
        NOCTALIA_PROJECT_ROOT="${SCRIPT_DIR}/../.."
    elif [ -f "/home/kotlin/Debian/patches/noctalia/Bar.qml" ]; then
        NOCTALIA_PROJECT_ROOT="/home/kotlin/Debian"
    else
        echo "WARNING: Cannot find project root. Set NOCTALIA_PROJECT_ROOT." >&2
        echo "  Example: export NOCTALIA_PROJECT_ROOT=/home/kotlin/Debian" >&2
        echo "  Or set:   export NOCTALIA_SOURCE=/path/to/noctalia-shell" >&2
    fi
fi

NOCTALIA_SOURCE="${NOCTALIA_SOURCE:-}"
PATCH_DIR="${NOCTALIA_PROJECT_ROOT}/patches/noctalia"
VENDOR_DIR="${NOCTALIA_PROJECT_ROOT}/vendor/noctalia/plugins"

# ── Determine Noctalia Source ─────────────────────────────────────────────────
if [ -z "${NOCTALIA_SOURCE}" ]; then
    for candidate in \
        "${HOME}/noctalia-shell" \
        "/usr/local/share/noctalia-shell" \
        "/usr/share/noctalia-shell" \
        "/opt/noctalia-shell"; do
        if [ -d "${candidate}" ]; then
            NOCTALIA_SOURCE="${candidate}"
            break
        fi
    done
fi

if [ -z "${NOCTALIA_SOURCE}" ] || [ ! -d "${NOCTALIA_SOURCE}" ]; then
    echo "ERROR: Cannot find Noctalia Shell source directory." >&2
    echo "Set NOCTALIA_SOURCE or clone it:" >&2
    echo "  git clone https://github.com/noctalia-dev/noctalia-shell.git" >&2
    echo "  cd noctalia-shell && cmake -B build && cmake --build build && sudo cmake --install build" >&2
    echo "  export NOCTALIA_SOURCE=\$(pwd)/noctalia-shell" >&2
    exit 1
fi

if [ ! -x "${QUICKSHELL_BIN}" ]; then
    echo "ERROR: QuickShell binary not found at ${QUICKSHELL_BIN}" >&2
    echo "Install QuickShell first: https://git.outfoxxed.me/quickshell/quickshell" >&2
    exit 1
fi

# ── Build Patched Config ──────────────────────────────────────────────────────
if [ ! -d "${CACHE_DIR}" ] || [ ! -f "${CACHE_DIR}/.patched" ]; then
    echo "Building patched Noctalia config in ${CACHE_DIR}..." >&2
    rm -rf "${CACHE_DIR}"
    mkdir -p "${CACHE_DIR}"

    cp -r "${NOCTALIA_SOURCE}"/* "${CACHE_DIR}/"
    chmod -R u+w "${CACHE_DIR}"

    # Apply patches
    if [ -d "${PATCH_DIR}" ]; then
        declare -A PATCH_MAP=(
            ["AllBackgrounds.qml"]="Modules/MainScreen/Backgrounds/AllBackgrounds.qml"
            ["Bar.qml"]="Modules/Bar/Bar.qml"
            ["BarContentWindow.qml"]="Modules/MainScreen/BarContentWindow.qml"
            ["LauncherCore.qml"]="Modules/Panels/Launcher/LauncherCore.qml"
            ["MainScreen.qml"]="Modules/MainScreen/MainScreen.qml"
            ["ThemeIcons.qml"]="Commons/ThemeIcons.qml"
        )

        for patch_file in "${PATCH_DIR}"/*.qml; do
            patch_name="$(basename "${patch_file}")"
            target_rel="${PATCH_MAP[${patch_name}]:-}"
            if [ -n "${target_rel}" ]; then
                target="${CACHE_DIR}/${target_rel}"
                if [ -f "${target}" ]; then
                    cp "${patch_file}" "${target}"
                    echo "  Patched: ${target_rel}" >&2
                else
                    echo "  WARNING: Target not found: ${target_rel}" >&2
                fi
            else
                echo "  WARNING: No mapping for patch: ${patch_name}" >&2
            fi
        done

        # Apply LauncherCore color substitutions
        launcher_core="${CACHE_DIR}/Modules/Panels/Launcher/LauncherCore.qml"
        if [ -f "${launcher_core}" ]; then
            sed -i \
                -e "s/color: entry.isSelected ? Color.mOnHover : Color.mOnSurfaceVariant/color: Color.mOnSurfaceVariant/g" \
                -e "s/color: entry.isSelected ? Color.mOnHover : Color.mOnSurface/color: Color.mOnSurface/g" \
                -e "s/color: gridEntryContainer.isSelected ? Color.mOnHover : Color.mOnSurface/color: Color.mOnSurface/g" \
                "${launcher_core}"
        fi

        # Apply PluginService auto-update patch
        plugin_service="${CACHE_DIR}/Services/Noctalia/PluginService.qml"
        if [ -f "${plugin_service}" ]; then
            sed -i "s/if (updateCount > 0) {/if (Settings.data.plugins.autoUpdate \&\& updateCount > 0) {/g" "${plugin_service}"
        fi
    fi

    # Copy vendored plugins
    if [ -d "${VENDOR_DIR}" ] && [ -d "${NOCTALIA_CONFIG_DIR}/plugins" ]; then
        cp -r "${NOCTALIA_CONFIG_DIR}/plugins"/* "${CACHE_DIR}/Modules/Panels/Plugins/" 2>/dev/null || true
    fi

    date > "${CACHE_DIR}/.patched"
    echo "Patched config built successfully" >&2
fi

# ── Include user config path ──────────────────────────────────────────────────
QUICKSHELL_ARGS=()
if [ -d "${NOCTALIA_CONFIG_DIR}" ]; then
    QUICKSHELL_ARGS+=(--path "${NOCTALIA_CONFIG_DIR}")
fi
QUICKSHELL_ARGS+=(--path "${CACHE_DIR}")

# ── Environment ───────────────────────────────────────────────────────────────
export XDG_ICON_THEME="${XDG_ICON_THEME:-Papirus-Dark}"
export ICON_THEME="${ICON_THEME:-Papirus-Dark}"
export QS_ICON_THEME="${QS_ICON_THEME:-Papirus-Dark}"

# ── Launch ────────────────────────────────────────────────────────────────────
exec "${QUICKSHELL_BIN}" "${QUICKSHELL_ARGS[@]}" "$@"
