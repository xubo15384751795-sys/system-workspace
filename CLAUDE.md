# CLAUDE.md

Project context for agents working in the Structural Risk Workbench (`System/`).

Before code changes, read the smallest sufficient context:

1. `MODULES.md` — pick the owning module
2. `module_contexts/<module>.md` — module scope and boundaries
3. `ROUTING_CONSTITUTION.md` — sparse activation and evidence rules
4. `packages/workbench/contracts/workbench/agent_prompt_sections/constitution.md` — workbench agent constitution

Live layers are Workbench, Harvester, and Protocols. Deformation v1 is a
historical evidence archive, not a live consumer of admitted evidence.

## Execution (local default)

Default execution is **local** on this Mac (`/Users/a1/Verity`).

1. **Edit and run here**: tests, scripts, dry-runs, and pipelines use the local Python 3.13 environment (`.venv`, `uv run`, or `make test`).
2. **Do not sync or SSH to `ai-box` unless the operator explicitly asks.**
3. Remote compute stays deferred until the local daily path is stable and running. `./scripts/sync_to_ai_box.sh` remains an opt-in path for that later stage.



Behavioral guidelines below reduce common LLM coding mistakes. Merge with module-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:

- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:

- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:

- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:

- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:

```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

## 5. Intent Resolution — Understand Before Acting

When the user's request is vague or ambiguous, do NOT immediately ask "what do you mean?" and do NOT blindly execute. Follow this decision tree:

### Layer 1: Contextualize (no user interaction)

Before asking anything, check the environment for signals:

- `Output/current/` — what was the last run? What changed recently?
- `Data/system_index/` — what data is available?
- `git log --oneline -10` — what was recently touched?
- `MODULES.md` — which module owns this request?

If the context resolves the ambiguity, proceed. Example: "check the latest run" → look at `Output/current/`, not ask "which run?"

### Layer 2: Explore (read-only, no user interaction)

If context doesn't resolve it, explore the relevant module before asking:

- Read `module_contexts/<module>.md` for scope
- Scan the relevant source directory with `Glob`/`Grep`
- Read the last 2-3 output files to understand current state

Report what you found, then propose an interpretation. Example: "优化一下数据流" → scan `packages/harvester/src/` and `Data/harvester/exports/`, then say "我看到 Harvester 最近的输出是 X，你是指优化抓取频率还是输出格式？"

### Layer 3: Propose (structured choices, not open questions)

If exploration doesn't resolve it, present **concrete options with a recommendation**:

- List 2-3 specific interpretations
- Mark one as "(推荐)" based on context
- Use the format: "我理解你可能是指：A (推荐) / B / C"

Do NOT ask open-ended questions like "你想做什么？" — always anchor with options.

### Layer 4: Confirm before high-impact actions

Before actions that affect multiple modules, cross boundaries, or change schemas:

- State what you're about to do
- State which module/files will be affected
- Wait for confirmation

This applies to: changes to `protocols/`, cross-module data flow modifications, new file creation outside the owning module, changes to `configs/`.

### Layer 5: Just do it (trivial tasks)

Skip all of the above for:

- Single-file reads or searches
- Questions with obvious answers from the codebase
- Tasks where the user gave specific file paths or function names
- "Run the tests" / "Show me the output" / "Check X"

### The principle

**Explore is cheaper than asking. Context is cheaper than exploration. Only ask when context + exploration both fail.**

---

Derived from [Andrej Karpathy's observations on LLM coding pitfalls](https://x.com/karpathy/status/2015883857489522876), as packaged in [multica-ai/andrej-karpathy-skills](https://github.com/multica-ai/andrej-karpathy-skills).
