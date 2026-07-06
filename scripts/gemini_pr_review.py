#!/usr/bin/env python3
"""
gemini_pr_review.py
====================

Beginner-friendly Proof-of-Concept PR review bot powered by the FREE Gemini
API (Google AI Studio). This script is invoked by
`.github/workflows/gemini-pr-review.yml` on every PR open/update.

What this script does, step by step:
  1. Reads configuration (API key, tokens, PR number, repo) from environment
     variables set by the workflow.
  2. Fetches the list of changed files + diffs ("patches") for the PR using
     the GitHub REST API.
  3. Loads our custom review rules from `review-rules.md` at the repo root.
  4. Sends the diff + rules to Gemini and asks it to respond with a JSON
     array of "findings" (file, line, severity, message).
  5. Parses that JSON safely (falls back gracefully if Gemini's response
     isn't valid JSON).
  6. Posts each finding back to the PR:
       - As an inline "review comment" anchored to the diff line, when we
         can figure out a valid diff position.
       - Otherwise, as a plain issue comment mentioning the file/line/message.
  7. Posts one summary comment at the top of the PR with counts per severity.

This script is intentionally written in a straightforward, linear style
(rather than heavily abstracted) so a beginner can read top-to-bottom and
understand exactly what's happening. Every external call is wrapped in
error handling so a single failure (bad API key, malformed JSON, network
hiccup) doesn't crash the whole GitHub Action.
"""

import json
import os
import re
import sys

import requests

# -----------------------------------------------------------------------------
# Try to import the Gemini SDK. We wrap this in a try/except so that if the
# dependency somehow isn't installed, we fail with a clear message instead of
# a confusing traceback.
# -----------------------------------------------------------------------------
try:
    import google.generativeai as genai
except ImportError:
    print("ERROR: google-generativeai package is not installed. "
          "Check the workflow's 'Install Python dependencies' step.")
    sys.exit(1)


# =============================================================================
# STEP 0: Read configuration from environment variables
# =============================================================================
# These are all set by .github/workflows/gemini-pr-review.yml. We read them
# up front and validate that the required ones are present, so we can print
# a helpful error message instead of crashing deep inside the script later.
# =============================================================================

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
PR_NUMBER = os.environ.get("PR_NUMBER")
REPO = os.environ.get("REPO")  # format: "owner/repo"

# Name of the Gemini model to use. gemini-2.0-flash is fast and free-tier
# friendly. If you don't have access to it yet, try "gemini-1.5-flash".
GEMINI_MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")

# Path to the review rules file (beginner-editable, at repo root).
REVIEW_RULES_PATH = os.environ.get("REVIEW_RULES_PATH", "review-rules.md")

GITHUB_API_BASE = "https://api.github.com"


def fail_gracefully(message):
    """
    Print an error message and exit WITHOUT raising an unhandled exception.
    We use exit code 0 here on purpose in most call sites (see comments
    below) so that a Gemini/API hiccup doesn't mark the whole PR check as
    "failed" for what is just a best-effort bot review. Adjust to exit(1)
    if you'd rather have failures show up as a red X on the PR.
    """
    print(f"ERROR: {message}")
    sys.exit(0)


# Validate required env vars up front.
if not GEMINI_API_KEY:
    fail_gracefully(
        "GEMINI_API_KEY is not set. Did you add it as a repo secret? "
        "See README-gemini-poc-setup.md for instructions."
    )
if not GITHUB_TOKEN:
    fail_gracefully("GITHUB_TOKEN is not set (this should be automatic in Actions).")
if not PR_NUMBER:
    fail_gracefully("PR_NUMBER is not set — this script must be run from a pull_request workflow.")
if not REPO:
    fail_gracefully("REPO is not set (expected 'owner/repo').")

try:
    OWNER, REPO_NAME = REPO.split("/", 1)
except ValueError:
    fail_gracefully(f"REPO env var '{REPO}' is not in 'owner/repo' format.")


# -----------------------------------------------------------------------------
# Shared HTTP headers for all GitHub REST API calls.
# -----------------------------------------------------------------------------
GITHUB_HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


# =============================================================================
# STEP 1: Fetch the PR's changed files + diffs from the GitHub REST API
# =============================================================================
def get_pr_files():
    """
    Calls GitHub's "List pull request files" endpoint to get every changed
    file in this PR, including its unified diff ("patch") when available.

    Docs: https://docs.github.com/en/rest/pulls/pulls#list-pull-requests-files

    Returns a list of dicts like:
        {
          "filename": "path/to/file.yaml",
          "status": "modified",
          "patch": "@@ -1,3 +1,4 @@\n ... unified diff text ...",
          "sha": "...",
        }

    Note: GitHub paginates this endpoint (max 100 files per page, up to
    3000 files total). For this PoC we fetch a few pages to be safe; very
    large PRs may still be truncated, which is fine for a beginner PoC.
    """
    files = []
    page = 1
    per_page = 100

    while True:
        url = f"{GITHUB_API_BASE}/repos/{OWNER}/{REPO_NAME}/pulls/{PR_NUMBER}/files"
        params = {"per_page": per_page, "page": page}

        try:
            response = requests.get(url, headers=GITHUB_HEADERS, params=params, timeout=30)
        except requests.RequestException as e:
            fail_gracefully(f"Network error fetching PR files: {e}")

        if response.status_code != 200:
            fail_gracefully(
                f"GitHub API error fetching PR files "
                f"(status {response.status_code}): {response.text}"
            )

        page_files = response.json()
        if not page_files:
            break

        files.extend(page_files)

        # If we got fewer than a full page, there are no more pages.
        if len(page_files) < per_page:
            break
        page += 1

        # Safety valve: don't loop forever on a huge/misbehaving PR.
        if page > 10:
            break

    return files


def get_pr_head_sha():
    """
    Fetches the PR's current head commit SHA. This is required by GitHub's
    "create review comment" endpoint (the `commit_id` field) so it knows
    exactly which commit an inline comment is anchored to.
    """
    url = f"{GITHUB_API_BASE}/repos/{OWNER}/{REPO_NAME}/pulls/{PR_NUMBER}"

    try:
        response = requests.get(url, headers=GITHUB_HEADERS, timeout=30)
    except requests.RequestException as e:
        fail_gracefully(f"Network error fetching PR metadata: {e}")

    if response.status_code != 200:
        fail_gracefully(
            f"GitHub API error fetching PR metadata "
            f"(status {response.status_code}): {response.text}"
        )

    return response.json().get("head", {}).get("sha")


# =============================================================================
# STEP 2: Load the review rules from review-rules.md
# =============================================================================
def load_review_rules():
    """
    Reads the beginner-editable review-rules.md file at the repo root and
    returns its text content. This becomes the "system prompt" / context we
    give Gemini so it knows what to look for.

    If the file is missing, we fall back to a minimal built-in rule set so
    the bot still works (just less tailored) instead of crashing.
    """
    if os.path.exists(REVIEW_RULES_PATH):
        try:
            with open(REVIEW_RULES_PATH, "r", encoding="utf-8") as f:
                return f.read()
        except OSError as e:
            print(f"WARNING: could not read {REVIEW_RULES_PATH}: {e}. Using fallback rules.")

    return (
        "# Fallback review rules\n"
        "- Flag hardcoded secrets/credentials.\n"
        "- Flag missing error handling.\n"
        "- Flag naming that isn't lowercase snake_case.\n"
        "- Flag breaking changes to existing behavior.\n"
    )


# =============================================================================
# STEP 3: Build the prompt and call the Gemini API
# =============================================================================
def build_diff_text(pr_files):
    """
    Turns the list of changed files (from get_pr_files) into one big text
    blob describing the diff, suitable for pasting into a prompt.

    We include the filename and its patch (unified diff). Some files (e.g.
    binary files, or files GitHub considers "too large") won't have a
    'patch' field — we skip those but still mention them so Gemini knows
    they changed.
    """
    chunks = []
    for f in pr_files:
        filename = f.get("filename", "<unknown file>")
        status = f.get("status", "unknown")
        patch = f.get("patch")

        if patch:
            chunks.append(
                f"### File: {filename} (status: {status})\n"
                f"```diff\n{patch}\n```\n"
            )
        else:
            chunks.append(
                f"### File: {filename} (status: {status})\n"
                f"(No text diff available — likely a binary file or too large to display.)\n"
            )

    return "\n".join(chunks)


def build_prompt(rules_text, diff_text):
    """
    Constructs the full prompt sent to Gemini. We explicitly ask for a JSON
    response with a fixed shape so we can parse it reliably in Python.
    """
    return f"""You are an automated pull request reviewer for a data pipeline repository.

Below are the project's review rules. Use them as your primary criteria when
reviewing the diff that follows.

--- REVIEW RULES START ---
{rules_text}
--- REVIEW RULES END ---

Below is the diff of changes in this pull request. Each section shows one
changed file and its unified diff (lines starting with "+" were added,
lines starting with "-" were removed).

--- DIFF START ---
{diff_text}
--- DIFF END ---

Review the diff against the rules above. Only report genuine issues found
IN THE DIFF (don't invent problems, and don't comment on unchanged code you
can't see). For each issue found, produce one finding.

Respond with ONLY a JSON array (no markdown fences, no extra prose) where
each element has exactly this shape:

[
  {{
    "file": "path/to/file.yaml",
    "line": 42,
    "severity": "issue" | "warning" | "nit",
    "message": "Short, specific explanation of the problem and suggested fix."
  }}
]

Rules for the "line" field:
- Use the line number IN THE NEW VERSION of the file (i.e. the line number
  as it will appear after this PR is merged), corresponding to an added
  ("+") line in the diff whenever possible.
- If you cannot confidently identify a specific line, set "line" to null.

Rules for "severity":
- "issue": something that should block merging (e.g. hardcoded secret,
  breaking change, missing error handling on critical path).
- "warning": worth fixing but not necessarily blocking.
- "nit": minor style/naming/cosmetic suggestion.

If you find no issues at all, respond with an empty JSON array: []

Respond with ONLY the JSON array, nothing else.
"""


def call_gemini(prompt_text):
    """
    Sends the prompt to the Gemini API and returns the raw text response.

    We wrap this in a try/except so that API errors (bad key, quota
    exceeded, network issues) are caught and handled gracefully rather than
    crashing the whole GitHub Action.
    """
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel(GEMINI_MODEL_NAME)
        response = model.generate_content(
            prompt_text,
            generation_config={
                # Ask Gemini to keep temperature low so it behaves more
                # consistently/deterministically for a review task.
                "temperature": 0.2,
                "max_output_tokens": 4096,
            },
        )
        return response.text
    except Exception as e:
        # Catches things like: invalid API key, rate limit / quota exceeded,
        # network timeouts, model-not-found, etc.
        print(f"ERROR: Gemini API call failed: {e}")
        return None


# =============================================================================
# STEP 4: Parse Gemini's JSON response (with a safe fallback)
# =============================================================================
def parse_findings(raw_text):
    """
    Attempts to parse Gemini's response as a JSON array of findings.

    Gemini sometimes wraps JSON in markdown code fences (```json ... ```)
    even when asked not to, so we strip those before parsing. If parsing
    still fails, we return an empty list AND a flag so the caller can post
    a "couldn't parse" fallback comment instead of crashing.
    """
    if not raw_text:
        return [], "Gemini returned an empty response."

    text = raw_text.strip()

    # Strip markdown code fences like ```json ... ``` or ``` ... ``` if present.
    fence_match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()

    try:
        findings = json.loads(text)
    except json.JSONDecodeError as e:
        return [], f"Could not parse Gemini's response as JSON ({e}). Raw response saved to logs."

    if not isinstance(findings, list):
        return [], "Gemini's response was valid JSON but not a list of findings as expected."

    # Validate + normalize each finding, skipping malformed entries instead
    # of crashing on one bad item.
    clean_findings = []
    for item in findings:
        if not isinstance(item, dict):
            continue

        file_path = item.get("file")
        message = item.get("message")
        if not file_path or not message:
            # Skip findings missing the bare minimum info we need.
            continue

        severity = str(item.get("severity", "warning")).lower()
        if severity not in ("issue", "warning", "nit"):
            severity = "warning"

        line = item.get("line")
        # Make sure "line" is an int or None (Gemini sometimes returns
        # strings like "42" or "N/A").
        if isinstance(line, str):
            line = int(line) if line.isdigit() else None
        elif not isinstance(line, int):
            line = None

        clean_findings.append({
            "file": file_path,
            "line": line,
            "severity": severity,
            "message": message,
        })

    return clean_findings, None


# =============================================================================
# STEP 5: Figure out valid "diff positions" for inline comments
# =============================================================================
def build_line_to_position_map(pr_files):
    """
    GitHub's "create review comment" API (for inline comments) can accept
    either a `line` number directly (for simple cases) on recent API
    versions, or requires a `position` (an offset into the unified diff)
    on older behavior. To keep this PoC robust, we compute, for each file,
    the set of NEW-file line numbers that are actually part of the diff
    (i.e. lines we're allowed to comment on), since GitHub only allows
    inline comments on lines that appear in the diff context.

    Returns a dict shaped like:
        {
          "path/to/file.yaml": {
              new_line_number: True,
              ...
          },
          ...
        }

    We parse each file's unified diff ("patch") by hand, tracking the
    running "new file" line counter as we walk through @@ hunks.
    """
    file_valid_lines = {}

    for f in pr_files:
        filename = f.get("filename")
        patch = f.get("patch")
        if not filename or not patch:
            continue

        valid_lines = set()
        new_line_num = None

        for raw_line in patch.split("\n"):
            # Hunk header, e.g. "@@ -12,7 +15,9 @@ some context"
            # The number after "+" is where the new-file line numbering
            # starts for this hunk.
            hunk_match = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", raw_line)
            if hunk_match:
                new_line_num = int(hunk_match.group(1))
                continue

            if new_line_num is None:
                # We haven't seen a hunk header yet — skip stray lines.
                continue

            if raw_line.startswith("+"):
                # An added line: it exists in the new file at new_line_num,
                # and is a valid target for an inline comment.
                valid_lines.add(new_line_num)
                new_line_num += 1
            elif raw_line.startswith("-"):
                # A removed line: doesn't exist in the new file, so the new
                # line counter does not advance.
                continue
            else:
                # A context (unchanged) line: exists in both old and new
                # files, and is also a valid comment target.
                valid_lines.add(new_line_num)
                new_line_num += 1

        file_valid_lines[filename] = valid_lines

    return file_valid_lines


# =============================================================================
# STEP 6: Post findings back to the PR
# =============================================================================
def post_inline_comment(finding, commit_sha):
    """
    Attempts to post an inline "review comment" on a specific file/line of
    the PR, using GitHub's "Create a review comment for a pull request"
    endpoint.

    Docs: https://docs.github.com/en/rest/pulls/comments#create-a-review-comment-for-a-pull-request

    Returns True on success, False on failure (caller should fall back to a
    general issue comment in that case).
    """
    severity_emoji = {"issue": "🔴", "warning": "🟡", "nit": "🔵"}
    emoji = severity_emoji.get(finding["severity"], "🟡")

    body = (
        f"{emoji} **Gemini PR Review [{finding['severity'].upper()}]**\n\n"
        f"{finding['message']}"
    )

    url = f"{GITHUB_API_BASE}/repos/{OWNER}/{REPO_NAME}/pulls/{PR_NUMBER}/comments"
    payload = {
        "body": body,
        "commit_id": commit_sha,
        "path": finding["file"],
        "line": finding["line"],
        "side": "RIGHT",  # comment against the new version of the file
    }

    try:
        response = requests.post(url, headers=GITHUB_HEADERS, json=payload, timeout=30)
    except requests.RequestException as e:
        print(f"WARNING: network error posting inline comment for {finding['file']}:{finding['line']}: {e}")
        return False

    if response.status_code in (200, 201):
        return True

    # This is expected to fail sometimes (e.g. the line isn't part of the
    # diff, or GitHub rejects the position for some other reason) — that's
    # exactly why we have a fallback comment path.
    print(
        f"WARNING: could not post inline comment for {finding['file']}:{finding['line']} "
        f"(status {response.status_code}): {response.text}"
    )
    return False


def post_issue_comment(body):
    """
    Posts a plain top-level comment on the PR's "Conversation" tab, using
    GitHub's standard issue-comments endpoint (pull requests are just
    issues under the hood for commenting purposes).

    Docs: https://docs.github.com/en/rest/issues/comments#create-an-issue-comment
    """
    url = f"{GITHUB_API_BASE}/repos/{OWNER}/{REPO_NAME}/issues/{PR_NUMBER}/comments"
    payload = {"body": body}

    try:
        response = requests.post(url, headers=GITHUB_HEADERS, json=payload, timeout=30)
    except requests.RequestException as e:
        print(f"WARNING: network error posting issue comment: {e}")
        return False

    if response.status_code in (200, 201):
        return True

    print(f"WARNING: could not post issue comment (status {response.status_code}): {response.text}")
    return False


def format_fallback_comment(fallback_findings):
    """
    Builds a single grouped comment for findings that couldn't be attached
    to a specific diff line (either because Gemini didn't give a line, or
    because GitHub rejected the inline comment). Grouping these into one
    comment avoids spamming the PR with lots of small comments.
    """
    severity_emoji = {"issue": "🔴", "warning": "🟡", "nit": "🔵"}

    lines = ["🤖 **Gemini PR Review — Additional Findings**",
             "",
             "The following findings couldn't be attached to a specific diff line, "
             "so they're listed here instead:", ""]

    for finding in fallback_findings:
        emoji = severity_emoji.get(finding["severity"], "🟡")
        location = finding["file"]
        if finding.get("line"):
            location += f":{finding['line']}"
        lines.append(f"- {emoji} **[{finding['severity'].upper()}]** `{location}` — {finding['message']}")

    return "\n".join(lines)


def format_summary_comment(findings, parse_error=None):
    """
    Builds the single top-of-PR summary comment, grouping findings by
    severity and printing counts. If there was a parse error or no findings
    at all, we adjust the message accordingly.
    """
    if parse_error:
        return (
            "🤖 **Gemini PR Review Summary**\n\n"
            f"⚠️ The review could not be completed cleanly: {parse_error}\n\n"
            "Check the GitHub Actions logs for this workflow run for the raw "
            "Gemini response, or see the Troubleshooting section of "
            "README-gemini-poc-setup.md."
        )

    if not findings:
        return (
            "🤖 **Gemini PR Review Summary**\n\n"
            "✅ No issues found against `review-rules.md`. Nice work!"
        )

    issue_count = sum(1 for f in findings if f["severity"] == "issue")
    warning_count = sum(1 for f in findings if f["severity"] == "warning")
    nit_count = sum(1 for f in findings if f["severity"] == "nit")

    lines = [
        "🤖 **Gemini PR Review Summary**",
        "",
        f"Found **{len(findings)}** finding(s) against `review-rules.md`:",
        f"- 🔴 Issues: {issue_count}",
        f"- 🟡 Warnings: {warning_count}",
        f"- 🔵 Nits: {nit_count}",
        "",
        "See inline comments on the **Files changed** tab (and any grouped "
        "fallback comment below) for details.",
    ]
    return "\n".join(lines)


# =============================================================================
# STEP 7: Main entry point — ties every step together
# =============================================================================
def main():
    print(f"Starting Gemini PR review for {OWNER}/{REPO_NAME} PR #{PR_NUMBER} "
          f"using model '{GEMINI_MODEL_NAME}'...")

    # ---- 1. Fetch the PR's changed files + diffs -----------------------------
    pr_files = get_pr_files()
    if not pr_files:
        print("No changed files found on this PR — nothing to review.")
        post_issue_comment(
            "🤖 **Gemini PR Review Summary**\n\n"
            "No changed files were found on this pull request, so there's "
            "nothing to review."
        )
        return

    # Filter out files with no usable text diff (binary/too-large files) —
    # there's nothing for Gemini to meaningfully review in those.
    files_with_patches = [f for f in pr_files if f.get("patch")]
    if not files_with_patches:
        print("None of the changed files have a text diff available — nothing to review.")
        post_issue_comment(
            "🤖 **Gemini PR Review Summary**\n\n"
            "None of the changed files in this PR have a text diff available "
            "(they may be binary or too large to display), so there's nothing "
            "for the automated reviewer to check."
        )
        return

    # ---- 2. Load review rules -------------------------------------------------
    rules_text = load_review_rules()

    # ---- 3. Build prompt and call Gemini --------------------------------------
    diff_text = build_diff_text(files_with_patches)
    prompt_text = build_prompt(rules_text, diff_text)

    raw_response = call_gemini(prompt_text)
    if raw_response is None:
        # call_gemini() already printed the underlying error to the logs.
        post_issue_comment(
            "🤖 **Gemini PR Review Summary**\n\n"
            "⚠️ The review could not run because the Gemini API call failed "
            "(invalid API key, rate limit, or a transient network issue). "
            "Check the Actions logs for this run for the exact error, or see "
            "the Troubleshooting section of README-gemini-poc-setup.md."
        )
        return

    # ---- 4. Parse the JSON response --------------------------------------------
    findings, parse_error = parse_findings(raw_response)
    if parse_error:
        print("Raw Gemini response (for debugging):")
        print(raw_response)
        post_issue_comment(format_summary_comment([], parse_error=parse_error))
        return

    if not findings:
        print("Gemini found no issues.")
        post_issue_comment(format_summary_comment([]))
        return

    print(f"Gemini returned {len(findings)} finding(s). Posting comments...")

    # ---- 5. Post inline comments where possible, fallback otherwise -----------
    commit_sha = get_pr_head_sha()
    valid_lines_by_file = build_line_to_position_map(files_with_patches)

    fallback_findings = []

    for finding in findings:
        file_valid_lines = valid_lines_by_file.get(finding["file"])
        can_try_inline = (
            commit_sha
            and finding["line"] is not None
            and file_valid_lines is not None
            and finding["line"] in file_valid_lines
        )

        posted_inline = False
        if can_try_inline:
            posted_inline = post_inline_comment(finding, commit_sha)

        if not posted_inline:
            fallback_findings.append(finding)

    if fallback_findings:
        print(f"Posting {len(fallback_findings)} finding(s) as a fallback grouped comment...")
        post_issue_comment(format_fallback_comment(fallback_findings))

    # ---- 6. Post the top-level summary comment ---------------------------------
    post_issue_comment(format_summary_comment(findings))

    print("Gemini PR review complete.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # Final safety net: absolutely nothing should crash this Action with
        # an unhandled traceback. If something truly unexpected happens, log
        # it clearly and exit(0) so the PR check doesn't fail on a best-effort
        # bot review.
        print(f"ERROR: unexpected failure in gemini_pr_review.py: {e}")
        sys.exit(0)