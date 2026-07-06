# CLAUDE.md — Automated PR Review Policy

This file tells Claude (running as the automated PR review agent via
`.github/workflows/claude-pr-review.yml`) how to review pull requests in this
repository. It is read automatically by the review workflow — see step 2 of
the prompt in that workflow file. Every section below is a placeholder
tuned for this repo; edit freely as the project evolves.

---

## 1. Project Context

<!--
CUSTOMIZE ME: Replace this section with a real description of what this repo
does. The review agent uses this to understand intent, so be specific about
what "correct" looks like for this codebase. Example filled in below for
albertsons/udco-spch — update it if the repo's purpose changes.
-->

- **Repo**: `albertsons/udco-spch`
- **Purpose**: Data pipeline configuration repo. Contains pipeline definitions
  for:
  - GCS → BigQuery ingestion
  - Kafka → BigQuery streaming ingestion
  - Orchestration via Airflow / Cloud Composer
  - Pipeline steps are declared as YAML files (e.g. `script_order_execution.yaml`)
    that get parsed by an internal orchestration framework and turned into
    Airflow DAG tasks.
- **Primary risk areas**: broken/invalid YAML that fails DAG parsing at
  deploy time, silently-changed schemas that break downstream BigQuery
  tables, and credentials/connection info accidentally committed to config.
- **Who reviews these PRs today**: data engineering team. Claude is an
  additional automated reviewer, not a replacement for human sign-off on
  schema or business-logic changes.

> If this section still says "GCS to BigQuery, Kafka to BigQuery..." after
> the pipeline architecture changes, update it — an out-of-date project
> context will cause Claude to review against the wrong assumptions.

---

## 2. Coding Standards & Conventions to Check

<!--
CUSTOMIZE ME: These are the concrete, checkable rules Claude enforces on
every diff. Add/remove rules as your team's conventions evolve. Keep each
rule specific enough that "did this PR violate it?" has a yes/no answer.
-->

### YAML formatting
- 2-space indentation, no tabs.
- No trailing whitespace; files end with a single trailing newline.
- Keys within a mapping are lowercase `snake_case` unless the schema
  consumed by the orchestration framework requires otherwise.
- Anchors/aliases (`&`, `*`) are allowed but must be used consistently
  within a file — don't mix anchor-based and copy-pasted duplicate blocks.
- No commented-out blocks of old pipeline steps left in committed YAML —
  delete dead config instead of commenting it out (git history preserves it).

### Naming conventions
- Pipeline/DAG file names: `snake_case.yaml`, named after the pipeline they
  define (e.g. `script_order_execution.yaml`, not `pipeline1.yaml`).
- Task/step IDs inside a pipeline YAML: `snake_case`, unique within the file,
  and descriptive of the action taken (e.g. `load_orders_to_bq`, not `step3`).
- BigQuery table/dataset references: fully qualified
  (`project.dataset.table`) — no bare table names that rely on an implicit
  default project/dataset.
- Kafka topic references: match the org's topic naming convention exactly
  (check for typos/case mismatches — these fail silently at runtime).

### Required fields
Flag a PR if a new or modified pipeline step is missing any of:
- A unique `task_id` / step identifier.
- An explicit `retries` / `retry_delay` (or documented reason it's
  intentionally omitted) — Composer tasks without retry config can fail
  pipelines on transient GCS/BigQuery/Kafka errors.
- A `schedule` or trigger definition for top-level pipeline configs.
- Source and destination fully specified (bucket/topic and
  dataset/table) — no partially-configured steps merged as "TODO."
- Owner/team tag or equivalent metadata field, if the schema supports one,
  so on-call can identify who to page.

---

## 3. Review Severity Rubric

<!--
CUSTOMIZE ME: This maps findings to the three review verdicts the workflow
can submit (APPROVE / COMMENT / REQUEST_CHANGES). Adjust thresholds to match
your team's risk tolerance — e.g. some teams treat "no error handling" as a
nit rather than blocking. As written here, it's tuned to be moderately
strict since this repo drives production data pipelines.
-->

### REQUEST_CHANGES (blocking — must be fixed before merge)
- Invalid or malformed YAML that would fail to parse.
- Hardcoded secrets, API keys, connection strings, or credentials anywhere
  in the diff (even in a comment or example value).
- A change that breaks or silently alters an **existing** pipeline step's
  behavior without an accompanying migration/backfill plan (e.g. renaming a
  destination table, changing a schema field type, changing partition keys).
- Missing error handling / retry config on a step that writes to BigQuery or
  reads from Kafka, where a transient failure would otherwise go unnoticed.
- Removing or reordering pipeline steps in a way that changes execution
  order or dependencies without clear justification in the PR description.
- Any logic that could cause data loss, duplication, or double-processing
  (e.g. missing idempotency key, no dedup on retry).

### COMMENT (non-blocking nits — flag but don't block)
- Minor formatting inconsistencies (indentation, key ordering) that don't
  break parsing.
- Naming that's technically valid but inconsistent with sibling files.
- Missing but non-critical metadata (e.g. a description field).
- Suggestions for readability, DRY-ing up repeated config via anchors, or
  better task naming.
- Style preferences where the existing repo has mixed precedent.

### APPROVE
- No blocking issues found, and any nits are truly cosmetic.
- New pipeline steps follow existing patterns in the repo, include required
  fields, and don't touch/break existing steps.
- Changes are additive-only or clearly backward compatible, with no
  ambiguity about downstream impact.

---

## 4. Always-Verify Checklist

<!--
CUSTOMIZE ME: This is the mechanical checklist Claude should run through on
every PR regardless of what "kind" of change it is. Treat this as a minimum
bar — add repo-specific checks over time as you notice recurring issues.
-->

On every PR, explicitly check and comment on each of the following:

- [ ] **No hardcoded secrets** — no API keys, passwords, tokens, service
      account JSON, or connection strings committed in plaintext anywhere in
      the diff (config values, comments, or example blocks included).
- [ ] **Error handling present** — new pipeline steps that call external
      systems (GCS, BigQuery, Kafka) define retry/error behavior, or the PR
      explains why it's intentionally omitted.
- [ ] **No breaking changes to existing pipeline steps** — existing
      `task_id`s, table/topic references, and step ordering are unchanged
      unless the PR explicitly intends to modify them, and the PR
      description acknowledges the impact.
- [ ] **Backward compatibility** — if a schema, table name, or field type is
      changing, confirm there's a migration path (dual-write, backfill,
      versioned table) rather than an in-place breaking change.
- [ ] **YAML validity** — the file would parse cleanly (correct nesting,
      quoting, no duplicate keys).
- [ ] **Required fields present** — see Section 2's "Required fields" list.
- [ ] **Consistency with existing files** — new pipeline definitions follow
      the same structural pattern as existing ones in the repo (don't
      introduce a one-off format).
- [ ] **No accidental scope creep** — the diff doesn't quietly modify
      unrelated pipelines/files beyond what the PR description describes.

---

## 5. Submitting the Review (Required — Do Not Skip)

<!--
CUSTOMIZE ME (lightly): This section describes *how* the review must be
submitted. The mechanics here are tied to the GitHub MCP tool wired up in
claude-pr-review.yml — don't remove this section, but feel free to adjust
the summary template/wording to match your team's preferred review style.
-->

**Every review must end with an actual submitted PR review — never just a
plain comment.** This is non-negotiable: the whole point of this bot is for
its verdict to appear in the PR's **Reviewers** sidebar (Approved / Changes
requested / Commented), the same way a human reviewer's would.

1. Do your analysis using the GitHub MCP tools (fetch diff, files, and
   existing review threads first, so you don't repeat prior feedback).
2. Decide a single overall verdict using the rubric in Section 3:
   `APPROVE`, `COMMENT`, or `REQUEST_CHANGES`.
3. Call the `pull_request_review_write` MCP tool **exactly once** per
   review run to submit a formal review with:
   - `event`: the verdict from step 2.
   - A structured top-level **summary** (see template below).
   - **Inline comments** anchored to the specific diff lines for every
     concrete issue found, each with a suggested fix where practical.
4. Do **not**:
   - Leave a plain issue comment instead of a review.
   - Call the review tool more than once for the same run.
   - Approve a PR that has any REQUEST_CHANGES-level issue open.

### Review summary template

Structure the top-level review summary like this, omitting any section with
no findings:

```
## Summary
One or two sentences: what this PR changes and the overall verdict.

## Logic
- [file:line] Issue description → suggested fix.

## Security
- [file:line] Issue description → suggested fix.

## Error Handling
- [file:line] Issue description → suggested fix.

## Style / Conventions
- [file:line] Issue description → suggested fix.

## Checklist
- Secrets check: ✅ / ❌ (details if failed)
- Error handling: ✅ / ❌
- Breaking changes to existing steps: ✅ none found / ❌ (details)
- Backward compatibility: ✅ / ❌
```

Keep the summary short and scannable — a reviewer skimming the PR sidebar
should understand the verdict and the biggest issue within a few seconds.