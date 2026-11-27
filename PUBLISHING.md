# EDHPod – automatic daily posting

How posts get from `queue/` to Instagram, and the one-time setup to switch it on.

## How it works

```
every 15 min   "Approvals" workflow
               ├─ new post in queue/?  → render it → Telegram: slides + caption + [✅ Approve] [❌ Reject]
               └─ you tapped?          → record approved.json / rejected.json in the repo

daily 17:00    "Daily post" workflow
UTC            ├─ today's post approved? no → Telegram: "not approved yet" (approve → posts immediately)
               ├─ rebuild from live Scryfall (fresh prices), render, alt text, compliance checks
               ├─ put slides on GitHub Pages (Instagram fetches images from a public URL)
               ├─ publish via the official Instagram API
               └─ Telegram: "✅ Published <link>"  or  "🚨 failed <log link>"

weekly         "Refresh Instagram token" workflow (the token expires after 60 days)
```

**What you do by hand:** tap Approve or Reject in Telegram. There are also two one-time steps the Instagram API can't do: pin the welcome post (a single tap, and Telegram reminds you) and paste the bio.

**Safety rules built in:**
- Nothing is posted without your approval.
- An approval covers the exact words you saw. If the post is edited afterwards, you get a new preview to approve.
- A post is never published twice.
- Every failure is reported on Telegram.

### Talking to the bot
| You send | What happens |
|---|---|
| tap ✅ / ❌ | Approve / reject. The message then shows "↩️ … instead" if you change your mind |
| any text right after a reject | Saved with the post as the note on what to change |
| `/status` | Queue overview: approved ●, needs review ○, rejected ✗, published ✓ |
| `/preview 2026-12-03` | Send that post's preview again (clears any earlier decision) |

Your taps are picked up within about 15 minutes; GitHub's timer is not exact. At most 5 previews are waiting at a time; the next ones arrive as you answer.

---

## One-time setup

Do the parts in this order. Each secret you create goes into the GitHub repo in Part 2, step 6.

### Part 1 — Telegram bot (5 minutes, phone)

1. In Telegram, search for **@BotFather** (it has a blue verified tick) and open the chat.
2. Send `/newbot`.
   - Name: `EDHPod Approvals`
   - Username: anything ending in `bot` that isn't taken, e.g. `edhpod_approvals_bot`
3. BotFather replies with a **token** like `7012345678:AAH…`. That's **`TELEGRAM_BOT_TOKEN`**. Keep it private; anyone who has it controls the bot.
4. Tap the `t.me/…` link in BotFather's reply to open your bot, and press **Start**.
5. Find your chat id. In the terminal on this machine:
   ```bash
   cd /work/u19d26/EDHPod
   python3 pipeline/telegram_bot.py whoami
   ```
   It asks for the token. Paste it and press Enter; nothing shows while you paste.
   It prints `chat id: 123456789`. That's **`TELEGRAM_CHAT_ID`**.

### Part 2 — GitHub (15 minutes, browser)

1. **Account.** Sign up at github.com if you don't have an account, and verify your email.
2. **Repository.** Click **+ → New repository**.
   - Name: `edhpod`
   - Visibility: **Public** (GitHub Pages is only free for public repos)
   - Leave "Add a README" unticked → **Create repository**
3. **Pages.** In the repo: **Settings → Pages → Build and deployment → Source: GitHub Actions**.
4. **Access token**, used for pushing from this machine and for the weekly token refresh. Click your avatar → **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**.
   - Name: `edhpod`. Expiration: the longest offered. Put the expiry date in your calendar.
   - Repository access: **Only select repositories → edhpod**
   - Repository permissions:
     - **Contents: Read and write**
     - **Secrets: Read and write**
     - **Workflows: Read and write**
   - **Generate token**, then copy it (`github_pat_…`). That's **`SECRETS_PAT`**, and also your password for `git push`.
5. **Push the code.** Tell Claude the repo URL; Claude makes the first commit. Then run this in the terminal yourself, so the token never passes through the chat:
   ```bash
   cd /work/u19d26/EDHPod
   git config credential.helper 'cache --timeout=3600'   # keeps the token in memory only, not on disk
   git push -u origin main
   ```
   When asked, **Username** is your GitHub username and **Password** is the `github_pat_…` token.
6. **Secrets.** In the repo: **Settings → Secrets and variables → Actions → New repository secret**. Create each of these:

   | Name | Value |
   |---|---|
   | `TELEGRAM_BOT_TOKEN` | from Part 1, step 3 |
   | `TELEGRAM_CHAT_ID` | from Part 1, step 5 |
   | `SECRETS_PAT` | from Part 2, step 4 |
   | `IG_ACCESS_TOKEN` | from Part 3 below |

   As soon as the two Telegram secrets exist, previews start arriving within about 15 minutes. You can approve posts before Instagram is connected.

### Part 3 — Instagram API token (20 minutes, browser)

You need a Facebook account to log in to Meta's developer site. Use your own; it doesn't appear anywhere on the channel.

1. Go to **developers.facebook.com** and log in. If it's your first time, click **Get started** and register as a developer (it confirms your email and phone).
2. **My Apps → Create app.**
   - App name: `EDHPod Publisher`. Contact email: yours.
   - Use case: **Manage messaging & content on Instagram**.
   - Business portfolio: **I don't want to connect a business portfolio yet**.
   - Continue through the summary → **Create app**. Re-enter your Facebook password if asked.
3. In the app's left menu, open **Use cases → Customize** next to the Instagram use case, or **Instagram → API setup with Instagram business login**.
   - If there is a button **Add all required permissions**, click it. You need `instagram_business_basic` and `instagram_business_content_publish`.
   - **If you only see "API setup with Unified login" and no Instagram-login option, stop and tell Claude.** That is a different token type, and the code would need adjusting.
4. Under **1. Generate access tokens → Add account**, log in as **@edhpod** in the popup and allow the access.
   - If Meta asks you to add an **Instagram Tester** role: choose it, search `edhpod`, click **Add**.
   - Then accept the invite in the Instagram app: **Settings → Website permissions / Apps and websites → Tester invites → Accept**.
   - Then refresh the developer page.
5. Click **Generate token** next to `edhpod`, log in again, and copy the token. It is shown **only once** and is valid for 60 days. The weekly workflow keeps renewing it.
6. Check it works:
   ```bash
   python3 pipeline/instagram.py whoami     # asks for the token; expect: @edhpod  user_id=…  type=MEDIA_CREATOR
   ```
7. Save it as the repo secret **`IG_ACCESS_TOKEN`** (Part 2, step 6).

Leave the app in **Development** mode. You don't need App Review or Business Verification to publish to your own account.

### Part 4 — Test without posting

1. Repo → **Actions → Daily post → Run workflow**.
   - Leave **dry run** ticked.
   - Tick **allow_unapproved**.
   - Enter the date of a queued post.
   - Click **Run workflow**.
2. A few minutes later Telegram says **🧪 Dry run OK**. That proves Instagram fetched the slides and accepted the post.
3. The next day, run **Actions → Refresh Instagram token** once by hand (the token must be at least 24 hours old) to prove the refresh works.

### Part 5 — Go live

1. Pick the launch date. Then run:
   ```bash
   cd /work/u19d26/EDHPod/pipeline
   python3 reschedule.py 2026-12-01 --apply
   git add -A ../queue && git commit -m "Launch dates" && git push
   ```
   This puts the welcome post first and the content posts on the following days. Approvals survive the move.
2. On launch day, paste the bio from `ACCOUNT-TEXT.md` into Instagram (the API can't edit the bio).
3. When Telegram says the welcome post is published: open it in Instagram → **⋯ → Pin to your profile**.

---

## Day to day

- Keep about a week approved ahead. `/status` shows the runway, and every publish message warns when fewer than 3 posts are left.
- **If you approve today's post after 17:00 UTC**, it goes out right away.
- **If a post was rejected, or its date passed**, close the gap with `python3 pipeline/reschedule.py <date> --apply`, then commit and push.
- **New content** is written by Claude into `queue/` as usual and pushed. The previews come to Telegram on their own.
- **Approving locally still works:** `python3 pipeline/approve.py <date>`, then commit and push.
- **Tokens:** the Instagram token renews itself weekly. The GitHub token (`SECRETS_PAT`) does not — renew it before the date in your calendar.

## Files

| File | Purpose |
|---|---|
| `pipeline/telegram_bot.py` | Previews, button handling, notifications |
| `pipeline/daily.py` | The daily job (`prepare` / `publish`) |
| `pipeline/instagram.py` | Instagram API client; `whoami`, `limit`, `refresh` |
| `pipeline/queuekit.py` | Post states: queued, approved, rejected, published |
| `pipeline/checks.py` | The automatable part of COMPLIANCE.md |
| `pipeline/alttext.py` | Alt text per slide |
| `pipeline/approve.py` | Queue overview and approval from the terminal |
| `pipeline/reschedule.py` | Move unpublished posts to new dates |
| `pipeline/build_welcome_post.py` | The pinned welcome / disclaimer post |
| `pipeline/test_publish.py`, `test_telegram.py` | Tests against fake Instagram and Telegram |
| `.github/workflows/` | `daily-post`, `approvals`, `refresh-token` |
