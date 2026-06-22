pragma Singleton

import QtQuick
import Quickshell
import qs.Commons

/*
 * Patch: make icon lookup accept both theme icon names and absolute file paths.
 * Noctalia upstream only resolves theme names via Quickshell.iconPath, so
 * .desktop files with Icon=/path/to/icon.png render as magenta placeholders.
 */
Singleton {
  id: root

  property real scoreThreshold: 0.2

  // Manual overrides for tricky apps
  property var substitutions: ({
                                 "code-url-handler": "visual-studio-code",
                                 "Code": "visual-studio-code",
                                 "com.google.Chrome.canary": "google-chrome-canary",
                                 "google-chrome-canary": "google-chrome-canary",
                                 "gnome-tweaks": "org.gnome.tweaks",
                                 "obs": "com.obsproject.Studio",
                                 "com.obsproject.Studio": "com.obsproject.Studio",
                                 "pavucontrol-qt": "pavucontrol",
                                 "pavucontrol": "pavucontrol",
                                 "org.pulseaudio.pavucontrol": "pavucontrol",
                                 "system-config-printer": "system-config-printer",
                                 "wps": "wps-office2019-kprometheus",
                                 "wpsoffice": "wps-office2019-kprometheus",
                                 "footclient": "foot",
                                 "qt5ct": "qt5ct",
                                 "qt6ct": "qt6ct",
                                 "rofi": "rofi",
                                 "rofi-theme-selector": "rofi",
                                 "printer-settings": "system-config-printer",
                                 "volume-control": "pavucontrol",
                                 "btop": "btop",
                                 "btop++": "btop",
                                 "qimgv": "qimgv",
                                 "yazi": "yazi",
                                 "protonup-qt": "protonup-qt",
                                 ".virt-manager-wrapped": "virt-manager",
                                 "virt-manager-wrapped": "virt-manager",
                                 "otd": "input-tablet",
                                 "open-tablet-driver": "input-tablet"
                               })

  // Dynamic fixups
  property var regexSubstitutions: [
    {
      "regex": /^steam_app_(\d+)$/,
      "replace": "steam_icon_$1"
    },
    {
      "regex": /Minecraft.*/,
      "replace": "minecraft-launcher"
    },
    {
      "regex": /.*polkit.*/,
      "replace": "system-lock-screen"
    },
    {
      "regex": /gcr.prompter/,
      "replace": "system-lock-screen"
    }
  ]

  property list<DesktopEntry> entryList: []
  property var preppedNames: []
  property var preppedIcons: []
  property var preppedIds: []

  Component.onCompleted: refreshEntries()

  Connections {
    target: DesktopEntries.applications
    function onValuesChanged() {
      refreshEntries();
    }
  }

  function refreshEntries() {
    if (typeof DesktopEntries === 'undefined')
      return;

    const values = Array.from(DesktopEntries.applications.values);
    if (values) {
      entryList = values.sort((a, b) => a.name.localeCompare(b.name));
      updatePreppedData();
    }
  }

  function updatePreppedData() {
    if (typeof FuzzySort === 'undefined')
      return;

    const list = Array.from(entryList);
    preppedNames = list.map(a => ({
                                    name: FuzzySort.prepare(`${a.name} `),
                                    entry: a
                                  }));
    preppedIcons = list.map(a => ({
                                    name: FuzzySort.prepare(`${a.icon} `),
                                    entry: a
                                  }));
    preppedIds = list.map(a => ({
                                  name: FuzzySort.prepare(`${a.id} `),
                                  entry: a
                                }));
  }

  function iconForAppId(appId, fallbackName) {
    const fallback = fallbackName || "application-x-executable";
    if (!appId)
      return iconFromName(fallback, fallback);

    const entry = findAppEntry(appId);
    if (entry) {
      return iconFromName(entry.icon, fallback);
    }

    return iconFromName(appId, fallback);
  }

  // Robust lookup strategy
  function findAppEntry(str) {
    if (!str || str.length === 0)
      return null;

    let result = null;

    if (result = checkHeuristic(str))
      return result;
    if (result = checkSubstitutions(str))
      return result;
    if (result = checkRegex(str))
      return result;
    if (result = checkSimpleTransforms(str))
      return result;
    if (result = checkFuzzySearch(str))
      return result;
    if (result = checkCleanMatch(str))
      return result;

    return null;
  }

  function iconFromName(iconName, fallbackName) {
    const fallback = fallbackName || "application-x-executable";
    var effective = iconName;

    // Apply substitutions to icon names (not only app IDs)
    if (effective && substitutions[effective]) {
      effective = substitutions[effective];
    }

    // 1) Accept absolute paths from .desktop files as real file URLs.
    // Plain "/nix/store/..." gets resolved by QML against the current qrc base,
    // which turns it into "qrc:/nix/store/..." and breaks image loading.
    if (effective && effective.startsWith("file:")) {
      return effective;
    }
    if (effective && effective.startsWith("/")) {
      return `file://${effective}`;
    }

    // 2) Normal theme lookup
    try {
      if (effective && typeof Quickshell !== 'undefined' && Quickshell.iconPath) {
        const p = Quickshell.iconPath(effective, fallback);
        if (p && p !== "")
          return p;
      }
    } catch (e) {}

    // 3) Fallback icon
    try {
      return Quickshell.iconPath ? (Quickshell.iconPath(fallback, true) || "") : "";
    } catch (e2) {
      return "";
    }
  }

  function distroLogoPath() {
    try {
      return (typeof OSInfo !== 'undefined' && OSInfo.distroIconPath) ? OSInfo.distroIconPath : "";
    } catch (e) {
      return "";
    }
  }

  // --- Lookup Helpers ---

  function checkHeuristic(str) {
    if (typeof DesktopEntries !== 'undefined' && DesktopEntries.heuristicLookup) {
      const entry = DesktopEntries.heuristicLookup(str);
      if (entry)
        return entry;
    }
    return null;
  }

  function checkSubstitutions(str) {
    let effectiveStr = substitutions[str];
    if (!effectiveStr)
      effectiveStr = substitutions[str.toLowerCase()];

    if (effectiveStr && effectiveStr !== str) {
      return findAppEntry(effectiveStr);
    }
    return null;
  }

  function checkRegex(str) {
    for (let i = 0; i < regexSubstitutions.length; i++) {
      const sub = regexSubstitutions[i];
      const replaced = str.replace(sub.regex, sub.replace);
      if (replaced !== str) {
        return findAppEntry(replaced);
      }
    }
    return null;
  }

  function checkSimpleTransforms(str) {
    if (typeof DesktopEntries === 'undefined' || !DesktopEntries.byId)
      return null;

    const lower = str.toLowerCase();

    const variants = [str, lower, getFromReverseDomain(str), getFromReverseDomain(str)?.toLowerCase(), normalizeWithHyphens(str), str.replace(/_/g, '-').toLowerCase(), str.replace(/-/g, '_').toLowerCase()];

    for (let i = 0; i < variants.length; i++) {
      const variant = variants[i];
      if (variant) {
        const entry = DesktopEntries.byId(variant);
        if (entry)
          return entry;
      }
    }
    return null;
  }

  function checkFuzzySearch(str) {
    if (typeof FuzzySort === 'undefined')
      return null;

    // Check filenames (IDs) first
    if (preppedIds.length > 0) {
      let results = fuzzyQuery(str, preppedIds);
      if (results.length === 0) {
        const underscored = str.replace(/-/g, '_').toLowerCase();
        if (underscored !== str)
          results = fuzzyQuery(underscored, preppedIds);
      }
      if (results.length > 0)
        return results[0];
    }

    // Then icons
    if (preppedIcons.length > 0) {
      const results = fuzzyQuery(str, preppedIcons);
      if (results.length > 0)
        return results[0];
    }

    // Then names
    if (preppedNames.length > 0) {
      const results = fuzzyQuery(str, preppedNames);
      if (results.length > 0)
        return results[0];
    }

    return null;
  }

  function checkCleanMatch(str) {
    if (typeof DesktopEntries === 'undefined' || !DesktopEntries.byId)
      return null;

    const lower = str.toLowerCase();

    const matches = [DesktopEntries.byId(str), DesktopEntries.byId(lower), DesktopEntries.byId(normalizeWithHyphens(str)), DesktopEntries.byId(str.replace(/_/g, '-').toLowerCase()), DesktopEntries.byId(str.replace(/-/g, '_').toLowerCase())];

    for (let i = 0; i < matches.length; i++) {
      if (matches[i])
        return matches[i];
    }
    return null;
  }

  // --- Utilities ---

  function fuzzyQuery(str, list) {
    const results = FuzzySort.go(str, list, {
                                     key: 'name',
                                     threshold: -1000,
                                     limit: 5
                                   });
    if (results && results.length > 0) {
      const best = results[0];
      if (best && best.score >= -scoreThreshold)
        return [best.obj.entry];
    }
    return [];
  }

  function normalizeWithHyphens(str) {
    return str.replace(/\./g, '-').replace(/_/g, '-');
  }

  function getFromReverseDomain(str) {
    if (!str || str.indexOf('.') === -1)
      return str;
    const parts = str.split('.');
    if (parts.length >= 2) {
      const reversed = parts.reverse().join('-');
      return reversed;
    }
    return str;
  }
}
