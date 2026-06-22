==================================================
MANDATORY VERIFICATION AND SELF-CHECK
==================================================

Before considering the task complete, you must verify your work against the repository and the generated Debian migration.

You are required to perform a full self-audit and confirm that nothing important was missed.

Verification requirements:

1. Cross-check the original repository against the migrated Debian project.
   - Every top-level folder must be reviewed.
   - Every meaningful NixOS/Home Manager module must be accounted for.
   - Every package from the source repo must be mapped or intentionally excluded with justification.
   - Every patch must be either preserved, replaced, or explicitly explained.
   - Every vendored resource must be either copied, packaged, or explicitly justified.
   - Every host/profile/module relationship must remain understandable in the Debian layout.

2. Produce a completeness checklist.
   For each item, mark one of:
   - migrated
   - replaced with equivalent
   - preserved as-is
   - requires manual action
   - not possible on Debian
   - intentionally omitted with reason

3. Validate functional equivalence.
   Confirm that the Debian result still covers:
   - Niri startup
   - Noctalia startup
   - shell/session startup flow
   - user configs
   - system configs
   - theming
   - portals/session plumbing
   - autostart behavior
   - custom package installs
   - patched components
   - launcher/keybind workflow

4. Verify file placement.
   Confirm that all generated files are in the correct Debian project locations and that the installer can find them.

5. Verify installer behavior.
   Check that the Python installer:
   - runs on Debian minimal
   - is idempotent
   - supports dry-run mode
   - supports backup
   - does not overwrite existing files silently
   - logs what it changed
   - fails clearly when a dependency is missing

6. Compare source and output.
   Before finishing, inspect the original repository again and ensure:
   - no important file was ignored
   - no config domain was dropped accidentally
   - no patch was lost
   - no package was forgotten
   - no critical startup command was skipped

7. If any gap remains, report it explicitly.
   Do not hide missing pieces.
   Do not claim success if the migration is only partial.
   Do not present an incomplete Debian port as 1:1.
   The final answer must clearly distinguish:
   - fully migrated items
   - partially migrated items
   - unresolved items
   - items that require manual follow-up

8. Final self-verification output.
   Include a short section titled "Verification Summary" that states:
   - what was checked
   - what matched
   - what did not match
   - what still needs manual review
