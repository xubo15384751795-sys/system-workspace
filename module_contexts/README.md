# Module Contexts

These files are short context packs for working inside the single `System/`
workspace. They do not replace the main README files. Their job is to route a
task to the right owner before reading source code.

Use this order:

1. Read `MODULES.md`.
2. Pick the smallest owning thread.
3. Read the matching file in this folder.
4. Read the listed protocols.
5. Inspect source files only inside the selected module.
6. Escalate only when the context file says to.

Files:

- `workbench.md`: product commands, current card, dashboards, artifact views.
- `framework.md`: Structural Deformation theory, operators, diagnostics.
- `harvester.md`: provider acquisition, provenance, data releases.
- `protocols.md`: schemas and contracts between modules.
- `data-output.md`: canonical data, run artifacts, promotion.
- `learning-hub.md`: governance memory and improvement records.
- `agent-routing.md`: sparse activation and agent workflow routing.

The guiding rule is simple: open one IDE folder, activate one logical module.
