# VOK Autopost

Automatic Middle East / trending news posts for **@vokoriginals** (Instagram) and the
**Vok** Facebook Page. Runs on GitHub's servers, so it works while your laptop is off.
Everything used is free.

## How a day works

| Time (PKT) | What happens |
|---|---|
| 07:20, 10:20, 13:20, 16:20, 19:20, 22:20 | **Make new posts**: finds the biggest stories (2+ outlets), Gemini writes headline + caption, a free photo is found, the VOK design is made, and each post is **emailed** to you (via a GitHub issue). Reply `ok` or `no` |
| Every 30 min, 09:07 to 23:37 | **Approve & publish**: reads your email replies, then posts the next approved post to Facebook + Instagram (one at a time, at least 25 min apart) |

- Up to **20 posts a day** (change `posts_per_day` in `config.json`).
- Not approved within 12 hours → **expired** (old news is skipped).
- If posting fails, you get an email with the reason.
- Only replies from the **vokoriginals-ai** account count. Others are ignored.

## Post status

`posts/<id>/post.json` → `pending` → `approved` / `rejected` → `published` (or `failed`, `expired`)

## Run something now

- **Make posts now:** Actions → *Make new posts* → Run workflow
- **Publish one post now:** Actions → *Approve & publish* → Run workflow → type the post folder name

## Secrets (Settings → Secrets and variables → Actions)

| Name | What |
|---|---|
| `META_PAGE_TOKEN` | Vok Page token (Graph API Explorer, app "VOK POSTER 2") |
| `GEMINI_API_KEY` | Free key from aistudio.google.com (project "vokapi") |
| *(GITHUB_TOKEN)* | Automatic; nothing to add. Used to open the approval emails/issues. |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Optional. Telegram approvals also work if these are ever added. |

## Rules built in

- Facts only from the collected source headlines/summaries; at least 2 outlets per story.
- Pakistan stories only when they're major global news.
- Engagement headlines, but never false; "killed/dead" written as "K!lled/D3ad" on the image.
- Photos: Wikimedia Commons / Openverse, free licences only, credited in the caption;
  no logos, maps, flags or historic archive images; no photo reused within 4 days.

## Files

- `vok/collect.py`: reads news feeds, groups and ranks stories
- `vok/write.py`: Gemini headline + caption (style rules live here)
- `vok/images.py`: free photo search
- `vok/render.py`: the VOK design
- `vok/gh.py`: email approvals (GitHub issues)
- `vok/telegram.py`: optional Telegram approvals
- `vok/publish.py`: Facebook + Instagram
- `vok/make_posts.py`, `vok/tick.py`: the two automatic jobs
- `config.json`: feeds, limits, posting hours


## Photos (how they are picked)
1. The person in the news: whoever gave the warning or statement, or the person the story is about.
   If no person is named, the country's current top leader.
2. If no free photo of them exists: a photo of the place or object (Strait of Hormuz, US Capitol...).
3. If still nothing safe and free: you get a **📷 photo needed** email. Open it in the GitHub app or
   website, write `ok`, attach a photo (and `credit: Reuters` if you like), and send. It is built
   and posted automatically. Email replies drop attachments, so use the app for these.
