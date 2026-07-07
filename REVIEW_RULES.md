# PR Review Rules

## Database & SQL
- Table and column names must be lowercase snake_case.
  Bad: `CREATE TABLE Users (UserID INT)` → Good: `CREATE TABLE users (user_id INT)`
- Every table must have a primary key and `created_at`, `updated_at` columns.
- Foreign keys follow `<table>_id` naming. Bad: `fk_usr` → Good: `user_id`
- No `SELECT *` in application code — name the columns.
- No string-built SQL. Bad: `f"WHERE name='{x}'"` → Good: parameterized queries.
- Migrations must include a rollback/down step.

## Code Quality
- No silently swallowed exceptions. Bad: `except Exception: pass` → Good: log or re-raise.
- No magic numbers. Bad: `if retries > 3` → Good: `MAX_RETRIES = 3`
- No `print()` debugging — use the logger.
- No commented-out code in the final diff.
- Public functions need type hints and docstrings.
- Files must be opened with context managers. Bad: `f = open(p)` → Good: `with open(p) as f:`

## Security
- No hardcoded secrets, API keys, tokens, or passwords.
- No `verify=False`, no `eval()`/`exec()` on dynamic input.
- Validate user input before use in queries, paths, or shell commands.

## Naming
- REST endpoints: kebab-case (`/user-orders`).
- Env variables: UPPER_SNAKE_CASE.
- Booleans read as questions (`is_active`, `has_permission`).

## PR Hygiene
- Flag PRs over ~500 changed lines: suggest splitting.
- New logic without tests: flag it.
- TODO/FIXME without a ticket reference: flag it.