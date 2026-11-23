# VOK Autopost

Automatic news posts for **@vokoriginals** (Instagram) and the **Vok** Facebook Page.
It runs on GitHub's servers, so it keeps working when your laptop is off.

## What's built so far

| Part | Status |
|---|---|
| Design engine: VOK template in code, smart photo crop, balanced headline | ✅ |
| Publisher: posts to Facebook + Instagram through Meta's official API | ✅ |
| Scheduler: checks every hour for approved posts that are due | ✅ |
| Story finder + caption writer (free Gemini API) | ⏳ next |
| Approvals on your phone | ⏳ next |

## How a post moves

```
posts/<post-id>/post.json   status: draft → approved → published
```

- **draft**: made, waiting for you
- **approved**: will go out at `publish_at` (Pakistan time), or on the next hourly run if empty
- **published**: done; links are saved in `post.json`
- **failed**: the error message is saved in `post.json`

## Publish one post right now

1. Open the **Actions** tab → **Publish posts** → **Run workflow**
2. Type the post folder name (e.g. `2026-11-23-cop31`) → **Run workflow**
3. Wait ~1–2 minutes. A green tick means it's live.

## Secrets (Settings → Secrets and variables → Actions)

| Name | What |
|---|---|
| `META_PAGE_TOKEN` | Vok Page access token (from Graph API Explorer, app "VOK POSTER 2") |
| `GEMINI_API_KEY` | Free key from aistudio.google.com (needed for the story writer, coming next) |

Never paste these anywhere else.

## Files

- `vok/render.py`: draws the post
- `vok/publish.py`: sends it to Facebook and Instagram
- `vok/run.py`: works through the queue
- `assets/`: Poppins font (open licence), logo, face-detection model
- `.github/workflows/publish.yml`: the hourly job
