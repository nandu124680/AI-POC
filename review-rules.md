# review-rules.md — Gemini PR Review Rules

<!--
CUSTOMIZE ME: This file is read directly by scripts/gemini_pr_review.py and
sent to the Gemini API as the review "rulebook" for every PR. Everything in
this file is plain text/markdown — Gemini just reads it as context, so you
can add, remove, or reword rules freely without touching any code.

This starter version is tuned for a data pipeline repo containing:
  - GCS -> BigQuery ingestion pipeline configs
  - Kafka -> BigQuery streaming ingestion pipeline configs
  - Airflow / Cloud Composer orchestration (YAML-defined pipeline steps)

Edit the sections below to match your actual repo's conventions. Keep rules
specific and checkable ("is this true or false about the diff?") so Gemini
can apply them consistently.
-->

## 1. Project Context

<!-- CUSTOMIZE ME: describe what this repo actually does. -->

- This repo contains pipeline configuration for:
  - GCS → BigQuery batch ingestion pipelines.
  - Kafka → BigQuery streaming ingestion pipelines.
  - Orchestration via Airflow / Cloud Composer, where pipeline steps are
    declared as YAML files and turned into DAG tasks by an internal
    orchestration framework.
- The biggest risks in this repo are: invalid YAML that fails DAG parsing at
  deploy time, silently broken/changed schemas that affect downstream
  BigQuery tables, and credentials accidentally committed to config files.
- This bot is a lightweight, best-effort automated reviewer. It does not
  replace human review — a data engineer should still review and approve
  schema or business-logic changes.

## 2. Naming Conventions

- Column / field names in YAML configs (e.g. schema definitions, mapping
  configs) must be **lowercase `snake_case`** (e.g. `order_id`, not
  `OrderID` or `order-id`).
- Pipeline/DAG file names should be `snake_case.yaml`, named after the
  pipeline they define (e.g. `script_order_execution.yaml`, not
  `pipeline1.yaml`).
- Task/step IDs inside a pipeline YAML must be `snake_case`, unique within
  the file, and descriptive of the action taken (e.g. `load_orders_to_bq`,
  not `step3` or `task_final_v2`).
- BigQuery table/dataset references should be fully qualified
  (`project.dataset.table`) rather than bare table names that rely on an
  implicit default project/dataset.
- Kafka topic names must exactly match the org's naming convention — flag
  anything that looks like a typo or case mismatch, since these fail
  silently at runtime rather than raising an error.

## 3. Required Fields

Flag a PR if a new or modified pipeline step is missing any of the
following:

- A unique `task_id` (or equivalent step identifier).
- Explicit `retries` / `retry_delay` configuration, or a clear comment/PR
  description explaining why it's intentionally omitted.
- A `schedule` or trigger definition for any new top-level pipeline config.
- Fully specified source and destination (e.g. bucket/topic name AND
  dataset/table name) — flag partially-configured steps that look like
  "TODO" placeholders.
- An owner/team metadata tag, if the schema supports one, so on-call
  engineers know who to contact.

## 4. Security

- **No hardcoded secrets, credentials, API keys, connection strings, or
  service account JSON** anywhere in the diff — including inside comments
  or "example" values. This should always be flagged as `issue` severity.
- No plaintext passwords or tokens in YAML config values, even temporarily
  ("just for testing").
- Watch for values that look like real credentials copy-pasted from a local
  `.env` file or cloud console (e.g. long base64-looking strings assigned to
  keys like `password`, `token`, `secret`, `key`).

## 5. Error Handling

- Any new pipeline step that reads from or writes to an external system
  (GCS, BigQuery, Kafka) should define retry/error-handling behavior, or the
  PR description should explain why it's intentionally left out.
- Flag missing dead-letter / error-topic handling on new Kafka consumer
  steps.
- Flag missing idempotency handling (e.g. no dedup key, no upsert/merge
  strategy) on steps that could be retried or re-run, since this can cause
  duplicate or double-processed data.

## 6. Breaking Changes

- Flag any change that renames or removes an **existing** `task_id`,
  destination table, or Kafka topic reference without an accompanying
  migration/backfill plan.
- Flag schema changes to existing BigQuery destination tables (e.g. changing
  a field's type, removing a field) that aren't clearly additive/backward
  compatible.
- Flag reordering or removal of existing pipeline steps that changes
  execution order or dependencies, unless the PR description clearly
  explains the intended impact.
- Additive-only changes (new steps, new optional fields) that don't touch
  existing steps are generally lower risk and should not be flagged as
  breaking.

## 7. YAML Hygiene

- YAML should use 2-space indentation, no tabs, and no trailing whitespace.
- No large commented-out blocks of old pipeline steps left in committed
  YAML — dead config should be deleted (git history preserves it), not
  commented out.
- Anchors/aliases (`&`, `*`) are fine but should be used consistently within
  a file rather than mixed with copy-pasted duplicate blocks.

## 8. Severity Guidance for This Bot

<!--
This section tells Gemini how to map issues to the "severity" field it
returns in JSON (issue / warning / nit). Adjust the bar to match your
team's risk tolerance.
-->

- **issue** (blocking-level problems): hardcoded secrets, invalid/malformed
  YAML, breaking changes to existing pipeline steps without a migration
  plan, missing error handling on a critical read/write path, anything that
  could cause data loss or duplication.
- **warning** (should be fixed, not necessarily blocking): missing
  non-critical required fields (e.g. missing owner tag), inconsistent
  naming, missing retry config with no explanation.
- **nit** (minor/cosmetic): formatting inconsistencies, naming that's valid
  but doesn't match sibling files, suggestions for readability or DRY-ing up
  config via YAML anchors.

---

<!--
Add your own project-specific rules below this line. The more specific and
concrete a rule is, the more reliably Gemini can check for it.
-->

## 9. Your Custom Rules

- (Add repo-specific rules here as your team identifies recurring issues.)