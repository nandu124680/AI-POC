# Gemini PR Review Bot — Beginner Setup Guide (Proof of Concept)

This document is a complete, beginner-friendly walkthrough for setting up the **Gemini PR Review Bot** in this repo. Unlike the Claude review agent (`claude-pr-review.yml` / `README-claude-review-setup.md`), this bot:

- Uses the **free** Gemini API from Google AI Studio (no billing account required to get started).
- Does **not** need a GitHub App, org admin access, or any Enterprise-specific setup.
- Does **not** show up in the PR "Reviewers" sidebar — it just posts regular PR comments (inline comments where possible, plus a summary comment) using the built-in `GITHUB_TOKEN`.

If you can create a repo secret and open a pull request, you can set this up in about 10 minutes.

---

## What you're setting up

Four files, already committed to this repo:

| File | Purpose |
|---|---|
| `.github/workflows/gemini-pr-review.yml` | The GitHub Actions workflow that runs on every PR. |
| `scripts/gemini_pr_review.py` | The Python script that fetches the diff, calls Gemini, and posts comments. |
| `review-rules.md` | Your editable rulebook — what the bot checks the diff against. |
| `README-gemini-poc-setup.md` | This guide. |

The only thing **you** need to do manually is create a free Gemini API key and add it as a GitHub Actions secret. Everything else is already wired up.

---

## (a) Create a free Gemini API key at Google AI Studio

1. Go to [https://aistudio.google.com/apikey](https://aistudio.google.com/apikey) in your browser.
2. Sign in with a Google account (a personal Gmail account works fine for a PoC; use a shared/team account if you want the key to outlive one person).
3. Click **Create API key**.
   - If prompted, choose to create the key in a new or existing Google Cloud project — for a PoC, either is fine, and you don't need to enable billing.
4. Copy the generated API key (a long string). You will not be able to see it again after leaving the page, so store it somewhere safe (e.g. a password manager) until you've added it to GitHub.
5. That's it — no billing setup is required to use the free tier. See the **Limitations** section below for what "free" means in practice (rate limits, quotas).

> Keep this key private. Anyone with this key can make API calls billed/rate-limited against your account. Never commit it directly into a file in this repo — it must only live in GitHub Secrets (next step).

---

## (b) Add the key as a GitHub Actions secret named `GEMINI_API_KEY`

1. In your web browser, go to this repository on GitHub.
2. Click **Settings** (top navigation bar of the repo — you need admin/write access to the repo to see this).
3. In the left sidebar, click **Secrets and variables** → **Actions**.
4. Click **New repository secret**.
5. Fill in:
   - **Name**: `GEMINI_API_KEY` (must match exactly — this is what `gemini-pr-review.yml` and `gemini_pr_review.py` expect).
   - **Secret**: paste the API key you copied from Google AI Studio.
6. Click **Add secret**.

You should now see `GEMINI_API_KEY` listed under **Repository secrets** (its value will be hidden/masked — that's expected).

> If you're setting this up across multiple repos, you can instead add this as an **organization secret** (Org Settings → Secrets and variables → Actions) and scope it to the relevant repos, so you don't have to repeat this step per repo.

---

## (c) Commit the four files to the repo

If you're reading this file, the other three files (`gemini-pr-review.yml`, `gemini_pr_review.py`, `review-rules.md`) should already exist in this repo at:

```
.github/workflows/gemini-pr-review.yml
scripts/gemini_pr_review.py
review-rules.md
README-gemini-poc-setup.md
```

If you're copying this setup into a **different** repo:

1. Copy all four files into the same relative paths in the target repo.
2. Commit and push them to your default branch (e.g. `main`) directly, or via a PR — either works, since the workflow only triggers on *pull requests*, not on pushes to `main`.
3. Double-check `review-rules.md` and edit it to match your project (see the comments inside that file — it's meant to be customized).

No other files need to change. Unlike the Claude setup, there's no GitHub App to register, no CODEOWNERS entry required, and no org-level installation step.

---

## (d) Set workflow permissions for pull-requests write access

The workflow file already declares the permissions it needs:

```yaml
permissions:
  contents: read
  pull-requests: write
```

This is usually sufficient on its own. However, some repos/orgs have a **repository-level** setting that can override or restrict what workflows are allowed to do, regardless of what's declared in the YAML. To make sure it's not blocking you:

1. Go to the repo's **Settings** → **Actions** → **General**.
2. Scroll down to **Workflow permissions**.
3. Make sure **"Read and write permissions"** is selected (not "Read repository contents permission only").
4. Click **Save** if you changed anything.

> If this is set to "Read-only" at the repo/org level, the bot's attempts to post comments will fail with a `403` error even though the workflow file looks correct — see the Troubleshooting section below.

---

## (e) Open a test PR to trigger it

1. Create a new branch:
   ```
   git checkout -b test-gemini-review
   ```
2. Make a small, intentionally imperfect change to test the bot — for example, edit a pipeline YAML file and:
   - Use a non-`snake_case` field name (e.g. `OrderID` instead of `order_id`).
   - Add a fake-looking hardcoded secret (e.g. `password: "hunter2"`) — **don't use a real secret, just a placeholder string**, to confirm the bot flags it.
3. Commit and push the branch:
   ```
   git add .
   git commit -m "Test Gemini PR review bot"
   git push origin test-gemini-review
   ```
4. Open a pull request from this branch into your default branch via the GitHub UI.
5. Go to the **Actions** tab in the repo and confirm a run named **"Gemini PR Review Bot (PoC)"** starts automatically. Click into it to watch the logs in real time.
6. Once it finishes (usually well under a minute for a small diff), go back to the **Files changed** and **Conversation** tabs of your PR to see the results (see next section).

---

## (f) What the output will look like

Once the bot runs successfully, you should see:

1. **Inline comments** on specific lines of the diff (in the **Files changed** tab), for findings where Gemini could confidently identify a line — each one looks like:

   > 🔴 **Gemini PR Review [ISSUE]**
   >
   > Hardcoded credential detected in `password` field — remove this value and use a secret manager / environment variable instead.

2. **A fallback list comment** (in the **Conversation** tab) for any findings that couldn't be attached to a specific diff line — grouped together in one comment so the PR isn't spammed with many small comments.

3. **One summary comment** at the top of the PR conversation, e.g.:

   > 🤖 **Gemini PR Review Summary**
   >
   > Found **3** finding(s) against `review-rules.md`:
   > - 🔴 Issues: 1
   > - 🟡 Warnings: 1
   > - 🔵 Nits: 1

If there are no issues at all, you'll just see a short "✅ No issues found" summary comment.

**Important:** the bot will **not** appear in the PR's "Reviewers" sidebar, and it will **not** approve or request changes on the PR — it only posts comments. This is by design for this lightweight PoC. Merging is unaffected by anything this bot posts unless you separately configure branch protection rules around required comments/checks.

---

## (g) Known limitations of the free Gemini tier

- **Rate limits**: The free tier (Google AI Studio API key) has a limited number of requests per minute and per day, which varies by model and can change over time. If you open many PRs in quick succession, or push many commits rapidly to the same PR, you may hit a rate limit and see the review fail for that run (the workflow will still finish without crashing — see error handling below).
- **Daily/monthly quota**: There's a cap on total free requests per day. Once exceeded, calls will fail until the quota resets. For a small team doing occasional PRs, this is usually not an issue; for a busy repo with many PRs per day, you may eventually need a paid tier or Google Cloud billing project.
- **Context/size limits**: Very large PRs (huge diffs, many changed files) may exceed the model's input token limit or produce a truncated/less reliable response. This PoC does not chunk large diffs — it sends everything in one prompt.
- **Non-determinism**: Even with a low temperature setting, Gemini's exact findings can vary slightly between runs on the same diff. Treat this bot as a helpful assistant, not a deterministic linter.
- **No conversation memory**: Each run is a fresh, independent call — the bot doesn't remember previous review comments on the same PR, so pushing a new commit may result in similar/duplicate-sounding comments on unchanged code if that code is still part of the diff context.
- **Not a substitute for human review**: This is a proof of concept meant to catch obvious issues (naming, missing fields, hardcoded secrets) — it is not a replacement for a data engineer reviewing schema or business-logic changes.

---

## (h) Troubleshooting

### "403" error when the bot tries to post a comment
- Check the workflow's `permissions:` block includes `pull-requests: write` (already set in `gemini-pr-review.yml` — don't remove it).
- Check **Settings → Actions → General → Workflow permissions** is set to "Read and write permissions" (see step (d) above). This is the most common cause of a 403 even when the YAML looks correct.
- If the PR comes from a **forked repository**, GitHub automatically gives the workflow a read-only token for security reasons — this is expected behavior and the bot will not be able to post comments on fork PRs. This workflow intentionally does not work around that (using `pull_request_target` instead would be a security risk), so it's designed to just quietly do nothing useful on fork PRs rather than fail loudly.

### "Invalid API key" or authentication errors from Gemini
- Double check the `GEMINI_API_KEY` secret is spelled exactly right (case-sensitive) in **Settings → Secrets and variables → Actions**.
- Make sure you copied the entire key with no extra spaces or line breaks when you pasted it into the GitHub secret.
- Try generating a new key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey) and replacing the secret value if you suspect it was revoked or mistyped.

### "Gemini API call failed" in the Action logs
- This usually means either an invalid key (see above), a rate limit/quota being hit (see Limitations), or a transient network issue. Check the exact error message printed in the **Actions** tab logs (click into the failed/completed run → the "Run Gemini PR review script" step).
- The script is designed to catch this and post a friendly summary comment on the PR (`⚠️ The review could not run because the Gemini API call failed...`) instead of crashing — if you see that comment, check the Action logs for the underlying error.

### JSON parse failures / no inline comments posted
- Occasionally Gemini's response won't be valid JSON (e.g. it adds extra commentary despite instructions not to). The script tries to strip common markdown code fences automatically, but if parsing still fails, it will post a summary comment saying so and print the raw response in the Action logs for debugging.
- If this happens often, try adjusting the prompt in `scripts/gemini_pr_review.py` (`build_prompt` function) to be even more explicit, or switch `GEMINI_MODEL` to a different model (e.g. from `gemini-2.0-flash` to `gemini-1.5-flash` or vice versa) by setting that environment variable in the workflow file.

### No comments posted at all, and no errors in the logs
- Check that the PR actually has changed files that GitHub reports a `patch` (diff) for — very large or binary files won't have a text diff, and if *all* changed files are like that, there's nothing for Gemini to review.
- Check `review-rules.md` exists at the repo root and is spelled correctly — if it's missing, the script falls back to a minimal built-in rule set (this isn't an error, just less tailored output).

### The bot commented, but I expected it to show up as a "Reviewer"
- This is expected and by design for this PoC — see the note at the end of section (f) above. If you need a bot identity that shows up in the Reviewers sidebar with an Approve/Request Changes verdict, see the separate Claude-based setup in `README-claude-review-setup.md`, which uses a GitHub App for that purpose.