You are a senior Linux migration engineer, Debian system integrator, NixOS/Home Manager reverse-engineer, and installer author.

Your job is to fully analyze the GitHub repository:
https://github.com/Redm00use/Nixdots

The target system is Debian MINIMAL, installed without any desktop environment, window manager, shell environment, or user-level graphical stack. The machine starts as a clean Debian base system. Your task is to rebuild the full Nixdots experience on top of that minimal Debian install.

The user wants the migration to preserve the current NixOS setup as closely as possible, with a strong preference for a 1:1 match in behavior, appearance, startup flow, configs, and desktop workflow.

This is not a superficial port. You must reverse-engineer the repository, understand its structure, map every meaningful NixOS/Home Manager feature to a Debian equivalent, and create a Python-based installer that can turn minimal Debian into the same Niri + Noctalia desktop environment.

==================================================
PRIMARY GOAL
==================================================

Create a Debian migration of this Nixdots repository that reproduces the current environment as faithfully as possible on a minimal Debian base system.

You must preserve:
- Niri window manager configuration
- Noctalia shell/panel behavior
- all user config files
- all system-level config files
- all patches, especially Noctalia-related patches
- all vendored dependencies and plugins
- all custom packages
- all theme assets and UI styling
- all startup behavior and autostart logic
- all shell environment behavior
- all practical desktop workflow details

If a feature cannot be matched exactly on Debian, document the exact limitation, the reason, the closest equivalent, and the remaining difference.

==================================================
BASE SYSTEM ASSUMPTION
==================================================

The target machine is Debian minimal only.

Assume:
- no graphical desktop environment is installed
- no display manager is installed
- no window manager is installed
- no shell environment customization is installed
- no user dotfiles are present
- no Niri, Noctalia, WezTerm, Yazi, Neovim, Zsh, Wayland extras, portals, theming stack, or helper tooling are preinstalled

Your installer must build everything needed on top of that bare minimum.

==================================================
REPOSITORY ANALYSIS REQUIREMENTS
==================================================

Before implementing anything, fully inspect the repository and produce an inventory of:

- the top-level directory structure
- every package used
- every service enabled
- every user service enabled
- every environment variable
- every shell alias/function
- every startup command
- every config file written into user space
- every config file written into system space
- every patch in `patches/`
- every vendored dependency in `vendor/`
- every custom package in `pkgs/`
- every reusable helper in `lib/`
- every host-specific override in `hosts/`
- every profile in `profiles/`
- every system module in `modules/nixos/`
- every Home Manager module in `modules/home-manager/`
- every static config in `config/`
- every helper or dev artifact in `dev/`
- every asset in `assets/`

You must understand how the repository is layered before translating it.

==================================================
EXPECTED REPOSITORY LAYERS
==================================================

Treat the repository as a layered system:

- `hosts/` = machine-specific configuration
- `profiles/` = roles and feature bundles
- `modules/nixos/` = system-level modules
- `modules/home-manager/` = user-level modules
- `config/` = static config files and runtime config templates
- `patches/` = source patches and local modifications
- `vendor/` = bundled third-party resources and plugins
- `pkgs/` = local package definitions
- `lib/` = helper logic and shared values
- `assets/` = wallpapers, visuals, and UI resources
- `dev/` = development helper files and tooling

Do not collapse these layers into one opaque script unless you also preserve the architecture in the Debian project.

==================================================
TARGET DESKTOP STACK
==================================================

The Debian migration must reconstruct the desktop stack that the Nixdots repo currently provides.

Preserve the user experience for:
- Niri
- Noctalia
- WezTerm
- Yazi
- Neovim
- Zsh
- Oh My Zsh or equivalent shell framework if that is what the repo uses
- theming and visual consistency
- portals, Wayland session plumbing, and desktop integration
- launchers, autostart, notifications, clipboard behavior, and session startup flow

Do not replace Noctalia with a different shell unless absolutely unavoidable. If replacement is unavoidable, state clearly that it is a fallback and not a 1:1 migration.

==================================================
MIGRATION RULES
==================================================

Convert NixOS/Home Manager concepts into Debian-native equivalents:

- NixOS packages -> apt packages, local builds, or source installs
- NixOS services -> systemd units, user units, or Debian config
- Home Manager programs -> dotfiles, XDG files, shell init files, desktop autostart entries
- Nix overlays -> local Debian build steps or pinned source installs
- Nix patches -> patch files applied during build/install
- Stylix/theme data -> Debian theme, icon, font, terminal, and app theming setup
- session startup config -> minimal Debian login/session wiring

Prefer native Debian packages where possible.
Use source builds only when needed.
Do not invent replacements without checking the repository first.

==================================================
TASK SEQUENCE
==================================================

Step 1: Audit
Create a complete audit of the repo:
- what each folder does
- what each module or profile is responsible for
- what software is installed
- what services are enabled
- what user config is applied
- what patches and vendor assets exist
- what custom components must be preserved

Step 2: Mapping
Map every meaningful Nix/NixOS/Home Manager element to Debian:
- exact Debian package names when available
- exact systemd units when needed
- exact config file locations
- exact runtime directories
- exact build steps for custom software

Step 3: Compatibility decisions
For each important component, classify it as:
- direct port
- Debian equivalent
- source build
- vendored runtime copy
- manual workaround
- impossible to replicate exactly

Step 4: Debian project design
Create a clean Debian migration project structure such as:
- `installer/`
- `system/`
- `user/`
- `configs/`
- `patches/`
- `vendor/`
- `assets/`
- `scripts/`
- `templates/`

Use a structure that is maintainable and understandable.

Step 5: Python installer
Create a Python installer that:
- runs on Debian minimal
- installs all required packages
- sets up the graphical session from scratch
- installs Niri and Noctalia
- copies or symlinks configs into place
- applies patches deterministically
- installs vendored assets and plugins
- writes user dotfiles and XDG configs
- enables required systemd services and user services
- supports dry-run mode
- supports backups
- is idempotent
- avoids destructive overwrites by default
- handles missing dependencies gracefully
- logs clearly what it is doing

Step 6: Validation
Define how to verify the migration:
- Niri starts correctly
- Noctalia starts correctly
- startup commands run
- patches are active
- theming matches
- shortcuts work
- user apps launch
- services are enabled
- session plumbing works on a bare Debian install

==================================================
PATCH HANDLING
==================================================

All patches in `patches/` must be preserved or explicitly justified.

For each patch:
- identify the upstream file or component it modifies
- decide whether Debian still needs the patch
- preserve it in the Debian migration if needed
- apply it in a reproducible way
- do not silently drop it

If a patch can be replaced by a config option, say so clearly.

==================================================
CUSTOM PACKAGE HANDLING
==================================================

Inspect all local packages in `pkgs/`.

For each package:
- determine whether Debian already has an equivalent
- determine whether it must be built from source
- determine whether it is a fork, wrapper, or vendor copy
- preserve it in the migration if needed
- document the install path and build path

==================================================
NOCTALIA + NIRI REQUIREMENTS
==================================================

This migration must preserve the Niri + Noctalia experience.

For Niri:
- preserve keybindings
- preserve workspaces
- preserve monitor behavior
- preserve startup commands
- preserve focus/tiling/layout semantics
- preserve launcher integration and session behavior

For Noctalia:
- preserve layout, panel behavior, widgets, plugins, and UI
- preserve QML/source patches
- preserve vendor resources
- preserve any custom modules or runtime wiring
- preserve theming and UX behavior

Do not weaken these requirements by replacing them with unrelated software unless there is no other option.

==================================================
OUTPUT REQUIREMENTS
==================================================

You must produce:

1. A repository audit report
2. A NixOS/Home Manager to Debian migration plan
3. A package/service/config mapping inventory
4. A Debian project layout proposal
5. A Python installer implementation
6. Any helper scripts required by the installer
7. A README that explains:
   - how to use the installer on Debian minimal
   - what it installs
   - what is automated
   - what still needs manual work
   - what cannot be replicated exactly
   - how backup and rollback work

==================================================
QUALITY BAR
==================================================

Be exact.
Be conservative.
Be explicit.

Do not:
- hand-wave missing pieces
- pretend a partial migration is complete
- silently omit patches or packages
- invent features not supported by the repo
- claim 1:1 parity unless it is actually achieved

If something is uncertain, inspect further.
If something cannot be matched on Debian, explain exactly why and give the closest equivalent.

==================================================
FINAL RESPONSE FORMAT
==================================================

When finished, provide:
- a concise summary of what was analyzed
- the migration decisions
- the Debian installer approach
- the biggest risks and gaps
- the generated project tree

Then provide the generated code and configuration files.

Start by analyzing the repository in detail.
Do not begin implementation until the repository structure and all migration targets are fully inventoried.
