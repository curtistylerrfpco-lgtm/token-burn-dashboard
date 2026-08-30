# Token Burn Dashboard

A local-first dashboard for understanding AI token usage by day, source, and type of work. It keeps exact measurements separate from estimates and turns raw usage totals into trends, source splits, peak days, and human-readable comparisons.

## What it shows

- Daily token-burn heatmap
- Weekly usage trend
- Totals, peak day, seven-day average, and active days
- Usage split across Codex, Gemini/OpenClaw, and ChatGPT
- Work-driver breakdowns such as shipping, research, review, and writing
- A detailed table for the latest 30 days
- Approximate scale comparisons to make large token counts easier to understand

## Data fidelity

The dashboard labels its sources so measured and estimated values are not presented as equivalent:

| Source | Fidelity | Method |
| --- | --- | --- |
| Codex | Exact | Reads token totals from the local Codex thread database and assigns them to each thread's last-updated day. |
| Gemini/OpenClaw | Exact | Aggregates `totalTokens` from local OpenClaw session records. |
| ChatGPT | Estimated | Reads a ChatGPT data export and estimates tokens from message text length at approximately four characters per token. |

All dates are normalized to `America/New_York`.

## Requirements

- Node.js 22 or newer
- pnpm 10
- Python 3.9 or newer for data refreshes

## Run locally

Install dependencies and start the development server:

```powershell
pnpm install
pnpm dev
```

Open [http://localhost:3000](http://localhost:3000).

Create a production build with:

```powershell
pnpm build
pnpm start
```

## Refresh dashboard data

On Windows, run:

```powershell
.\scripts\refresh-dashboard.ps1
```

The refresh process:

1. Reads locally available Codex and OpenClaw usage records.
2. Checks `D:\ChatGPT Export` first, then looks in common Downloads, Documents, and Desktop locations.
3. Applies any manual driver classifications from `data/driver-overrides.json`.
4. Rewrites `data/daily-burn.sample.json` and `data/source-status.json`.
5. Runs a production build to validate the refreshed data.

To use a specific ChatGPT export, set `CHATGPT_EXPORT_PATH` before refreshing:

```powershell
$env:CHATGPT_EXPORT_PATH = "C:\path\to\chatgpt-export.zip"
.\scripts\refresh-dashboard.ps1
```

### ChatGPT export inbox

The private ChatGPT export inbox is `D:\ChatGPT Export`. Download the account data ZIP from ChatGPT, place the ZIP in that folder without extracting it, and run:

```powershell
Set-Location "D:\Codex Projects\Active\Token Burn Dashboard"
.\scripts\refresh-dashboard.ps1
```

The ZIP may have any filename; it is only accepted when it contains `conversations.json` or modern split files such as `conversations-000.json`. Raw ChatGPT conversations stay in the D: drive inbox and are never copied into this repository. Only per-day estimated token totals are written to the dashboard data files.

## Publish refreshed data

The guarded publisher refreshes all local sources, validates the production build, commits only the two generated dashboard data files, and pushes `main` so Vercel can redeploy:

```powershell
.\scripts\publish-dashboard.ps1
```

For safety, publishing stops when the repository already contains changes, the current branch is not `main`, the remote cannot be fast-forwarded, the build fails, or the refresh changes an unexpected file. The computer must be awake and connected to the internet when a scheduled local run begins.

## Data format

The UI reads normalized daily rows from `data/daily-burn.sample.json`:

```json
{
  "date": "2026-07-03",
  "codex_tokens": 125000,
  "gemini_openclaw_tokens": 42000,
  "chatgpt_est": 18000,
  "total": 185000,
  "driver": "shipping",
  "evidence": "Codex exact, Gemini/Open Claw exact, ChatGPT estimated; scrubbed shipping day"
}
```

Supported driver labels are `video`, `review`, `research`, `planning`, `writing`, `support`, `admin`, and `shipping`.

Manual driver overrides use a date-to-driver map:

```json
{
  "2026-07-03": "review"
}
```

## Project structure

```text
app/                         Next.js interface
data/                        Normalized usage and source-status files
lib/                         Date windows, aggregation, and token math
scripts/refresh-dashboard.py Data collection and normalization
scripts/refresh-dashboard.ps1 Windows refresh and build helper
scripts/publish-dashboard.ps1 Guarded Git/Vercel publishing helper
```

## Privacy

The refresh scripts read usage data locally. The ChatGPT export inbox is outside this repository, so raw conversations are not included in Git or Vercel deployments. Before publishing or deploying, review the generated files and keep raw exports, environment files, private project names, and other sensitive metadata out of source control. Local Vercel metadata and environment files are excluded by `.gitignore`.

## Deployment

The project is configured for Next.js on Vercel. Once the GitHub repository is connected to a Vercel project, pushes to `main` can trigger production deployments and other branches can produce previews.
