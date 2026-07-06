# Claude PR Review Agent — Manual Setup Guide

This document covers the steps that **must** be done by hand in the GitHub Enterprise web UI (and Anthropic console) to stand up the "Claude PR Review Agent" so it appears in the PR **Reviewers** sidebar. These steps cannot be captured in version-controlled files — `claude-pr-review.yml` and `CODEOWNERS` in this repo assume the setup below already exists.

Complete these once at the org level (an org admin will need to perform most steps).

---

## 1. Get an Anthropic API key

1. Log into the [Anthropic Console](https://console.anthropic.com/) with the org's Anthropic account (use a dedicated billing/service account if possible, not a personal one).
2. Navigate to **API Keys** → **Create Key**.
3. Name it something identifiable, e.g. `github-claude-pr-review-agent`.
4. Copy the key value immediately — it will not be shown again.
5. Confirm the account has access to the target model (`claude-opus-4-5-20251101` — **double-check this exact model slug in the console's model list before go-live**, as it's used as a placeholder in the workflow and may not match the currently released identifier).
6. Set usage/spend limits or alerts on this key if your console supports it, since this key will be invoked automatically on every PR.

---

## 2. Create the GitHub App ("Claude Review Agent")

This is what gives the bot its own distinct identity (e.g. `claude-review-agent[bot]`) in the Reviewers sidebar, rather than showing up as generic `github-actions[bot]`.

1. Go to your GitHub Enterprise instance → your **organization** → **Settings** → **Developer settings** → **GitHub Apps** → **New GitHub App**.
   - On GHE Server, this may instead be under **Site admin** → **GitHub Apps** if you want an instance-wide (not just org-scoped) app — confirm with your GHE admin which is appropriate for your setup.
2. Basic info:
   - **GitHub App name**: `Claude Review Agent` (or your org's preferred naming convention).
   - **Homepage URL**: link to this repo or an internal docs page describing the bot.
   - **Webhook**: **disable** ("Active" unchecked) unless you plan to run an always-on service listening for events — this setup relies on Actions polling/triggering, not webhooks.
3. **Permissions** (Repository permissions):
   - **Contents**: Read-only
   - **Pull requests**: Read & write (required to submit reviews)
   - **Issues**: Read & write (required for `issue_comment` triggers / acknowledgment comments)
   - **Metadata**: Read-only (mandatory default)
   - Leave all other permissions at "No access" — least privilege.
4. **Where can this GitHub App be installed?** → select **Only on this account** (your org), not "Any account."
5. Click **Create GitHub App**.
6. On the resulting app settings page:
   - Note the **App ID** (numeric) — you'll store this as a secret.
   - Under **Private keys**, click **Generate a private key**. This downloads a `.pem` file — treat it like a password. You'll paste its contents into a secret in step 4 below.

---

## 3. Install the App at the org level

1. From the App's settings page, click **Install App** (left sidebar).
2. Select your organization.
3. Choose **All repositories** if every repo should get automated review, or **Only select repositories** to pilot with a subset first (recommended for initial rollout).
4. Confirm installation.
5. Verify install by checking **Org Settings** → **GitHub Apps** (or **Installed GitHub Apps**) — "Claude Review Agent" should be listed with the repos you selected.

---

## 4. Add org-level (or repo-level) secrets

Go to **Organization Settings** → **Secrets and variables** → **Actions** → **New organization secret**. For each secret, set the **repository access** policy to match your installation scope from step 3 (either "All repositories" or an explicit allow-list).

| Secret name | Value | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | The API key from step 1 | Required. |
| `CLAUDE_APP_ID` | The numeric App ID from step 2 | Required for the "bot identity" auth path (Option A in the workflow). |
| `CLAUDE_APP_PRIVATE_KEY` | Full contents of the downloaded `.pem` file (including `-----BEGIN/END PRIVATE KEY-----` lines) | Required for Option A. Keep this scoped as tightly as possible. |

If you're instead using the simpler PAT-based approach (Option C in the workflow), create:

| Secret name | Value | Notes |
|---|---|---|
| `CLAUDE_REVIEW_PAT` | A fine-grained PAT from a dedicated service/machine account | Grant it only `pull-requests: write`, `contents: read`, `issues: write` scoped to the relevant repos. Rotate periodically. |

For individual repos calling this as a reusable workflow (`workflow_call`), make sure their caller workflow uses `secrets: inherit` so these org secrets flow through automatically — no per-repo secret configuration should be needed if scoped correctly at the org level.

---

## 5. (Optional but recommended) Create the `@your-org/claude-review-agent` proxy team

Used by `CODEOWNERS` as a fallback in case your GHE version doesn't support listing a GitHub App directly as a code owner.

1. **Org Settings** → **Teams** → **New team**.
2. Name it `claude-review-agent` (so it resolves to `@your-org/claude-review-agent`).
3. Give the team **Write** access to the repos where CODEOWNERS references it (CODEOWNERS entries must have at least write access to be valid).
4. **Confirm with your GHE admin** whether:
   - The GitHub App itself can be added as a "member" of this team (some GHE versions support bot/app team membership; others don't), **or**
   - This team should instead just contain the humans who get pinged as a fallback/backup when the automated review doesn't run, with the actual bot review still delivered via the Actions workflow regardless of CODEOWNERS matching.
5. Update the placeholder `@your-org/claude-review-agent` and `@your-org/...` team handles throughout `CODEOWNERS` and this doc to match your actual org/team names.

---

## 6. Verify branch protection interaction

1. Go to the target repo(s) → **Settings** → **Branches** → edit the protection rule for your default/main branch.
2. Decide whether Claude's review should be:
   - **Advisory only** (recommended to start): don't check "Require review from Code Owners" as it applies to the Claude entries — let it post reviews without blocking merges.
   - **Blocking**: check **Require a pull request before merging** → **Require review from Code Owners**, which will make matching CODEOWNERS entries (including the Claude proxy team) required approvals.
3. Note that GitHub does not allow a single Actions-token-authored review to satisfy "require review from Code Owners" unless the reviewing identity is one of the actual listed owners — this is exactly why the GitHub App identity (step 2) matters if you want the bot's approval to count toward required reviews.

---

## 7. Pilot and confirm sidebar behavior

1. Open a small internal (non-fork) test PR in a pilot repo.
2. Confirm the workflow run triggers (`Actions` tab) and completes successfully.
3. Check the PR's **Reviewers** sidebar — you should see the bot identity (`claude-review-agent[bot]` if using the GitHub App path) listed with a review status (Approved / Changes requested / Commented).
4. Confirm inline comments landed on the correct diff lines.
5. Test the on-demand path by commenting `@claude review` on an existing PR and confirming a new review is posted.
6. Once satisfied, expand the App installation (step 3) and CODEOWNERS rollout to additional repos.

---

## Rollback / disabling

- To pause the bot org-wide without deleting anything: go to the GitHub App's install settings and suspend the installation, or remove/rename the secrets so the workflow fails closed.
- To remove per-repo: uninstall from that repo in the App's install settings, and remove the caller workflow / CODEOWNERS entries referencing `@your-org/claude-review-agent`.