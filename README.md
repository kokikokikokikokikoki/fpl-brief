# FPL Brief — auto data pipeline

Pulls your Fantasy Premier League squad, #club-football mini-league standings,
tracked rivals, and upcoming fixtures from the public FPL API. It writes a
human-readable `digest.md` plus structured snapshots under `data/`.

The GitHub Action refreshes `digest.md` every six hours and commits it back to
the repository. You can also run it manually from GitHub's Actions tab.

## Repo layout
```
your-repo/
├── fetch_fpl.py                  # the fetcher (no dependencies, stdlib only)
├── digest.md                     # generated output — Claude reads this
├── data/                         # generated snapshots and discussion records
├── dashboard/                    # zero-dependency localhost interface
├── dashboard.py                  # local dashboard server
├── start-dashboard.ps1           # Windows launcher
├── fpl_brief/                     # collection, analysis, rendering, storage
├── config.json                    # team, target league, and horizon settings
├── tests/
│   └── test_fetch_fpl.py          # offline regression checks
├── README.md
└── .github/workflows/
    └── fpl-digest.yml            # weekly cron + manual run
```

## One-time setup (~10 min)
1. Create a **public** GitHub repo (public so Claude can read the raw file).
   If you'd rather keep it private, that's fine too — just paste `digest.md`
   into chat each week instead.
2. Add `fetch_fpl.py` and `README.md` at the root.
3. Add `fpl-digest.yml` at `.github/workflows/fpl-digest.yml` and the `tests/`
   folder.
4. Your Team ID (`6572775`) and target league (`461748`, #club-football) are
   set in `config.json`. `FPL_TEAM_ID` overrides the team ID for one run.
5. Go to the repo's **Actions** tab → enable workflows → click
   **FPL Digest → Run workflow** once to generate the first `digest.md`.

## Run it locally (optional)
```bash
python fetch_fpl.py          # writes digest.md
FPL_TEAM_ID=1234567 python fetch_fpl.py   # any other team
```

## Local dashboard

The dashboard uses strict TypeScript and Vite for frontend development/builds;
the Python standard-library server remains the API and local production server.
The UI includes the squad, #club-football rivals, player pool, Wildcard lab,
Research Desk, Candidate Lens, and Decision Desk.

### Development mode

In PowerShell terminal 1, from the repository root:

```powershell
python dashboard.py
```

In terminal 2:

```powershell
cd dashboard
npm ci                 # first setup, or after package-lock.json changes
npm run dev
```

Open `http://127.0.0.1:5173`. Vite serves the TypeScript UI and proxies `/api/*`
to the Python server at `http://127.0.0.1:8765`.

### Build and serve the production bundle locally

```powershell
cd dashboard
npm ci
npm run typecheck
npm run build
cd ..
python dashboard.py
```

Open `http://127.0.0.1:8765`. Python serves only the generated `dashboard/dist/`
files. Until the bundle is built, every non-API page returns `503` with the
build command, rather than serving TypeScript source that browsers cannot run;
`/api/*` keeps working. `dashboard/dist/` and `dashboard/node_modules/` are
ignored by Git, so a fresh checkout always needs this build step.

### Private FPL account data (local only)

The public FPL API has no selling prices, free transfers, bank or chip status.
To add them yourself (about a minute, no Claude needed):

1. In **Overview → Your FPL account → Update from FPL**, open the link. It goes to
   `fantasy.premierleague.com/api/my-team/<your team id>/` in your normal browser,
   where you are already signed in to FPL.
2. Select all (Ctrl+A), copy, and paste it into the box, then click **Import**.

The server wraps and validates the data and saves `local/private_team.json`. That
folder is gitignored and never goes into the Docker image. Only the team data is
read, never a password or token.

The import endpoint only accepts requests that are:
- sent to a loopback-bound server;
- from this dashboard's own origin (Origin/Referer, with the Host checked to
  block DNS rebinding);
- `application/json`, 64 KB at most.

Account data is used while it is fresh: less than 24 hours old
(`private_stale_after_hours`), with no deadline passed since capture, and a
squad that matches the public snapshot. Otherwise the panel explains why.
Claude can also capture it for you from its browser pane.

### Weekly workflow

1. **Refresh FPL data** (top right). Then refresh your account data as above.
2. **My squad** shows the board: the suggested XI, bench order, captain and the
   changes from your saved lineup. It also has:
   - a captain shortlist with each player's next fixture;
   - a fixture strip (next three opponents, coloured by FPL difficulty) when you
     pick up a shirt.
   Drag shirts to try your own XI.
3. **Candidate lens**: choose a player to replace, then click **Try on board** on
   a candidate. My squad then shows a **Planned transfers** strip:
   - up to three moves;
   - checked against position, availability, the three-per-club limit and your
     real budget (selling prices plus bank);
   - the best XI and captain with those players;
   - the next-gameweek FPL estimate change after any −4 hits.
   Plans are saved in this browser only.
4. For team news and judgement (press conferences, rotation), ask Jev (Claude)
   in Claude Code.
5. Make the real changes in the FPL app; this dashboard never changes your team.

### Container image (Railway-compatible)

The root `Dockerfile` builds the bundle on the host. A Node stage runs `npm ci`,
the typecheck, and `vite build`. The runtime stage is Python-only: it copies
the application, `data/`, `config.json`, and the built `dashboard/dist/`, and
runs `python dashboard.py` as a non-root user. `.dockerignore` is an allowlist.
Railway uses a root `Dockerfile` in preference to `Procfile`, which remains
only for running Python directly. To smoke-test locally:

```powershell
docker build -t fpl-brief:local .
docker run --rm -e PORT=8080 -p 127.0.0.1:8080:8080 fpl-brief:local
```

**Render (current host).** `render.yaml` is a Blueprint for a free Docker web
service. It auto-deploys on every commit to `main` and uses the `/healthz`
healthcheck (unauthenticated, no data, 200 only when the frontend bundle is
built). To set it up in Render: New → Blueprint → choose this repo → Apply.

The site is password-protected (Overseer decision 2026-09-26):
- Set `DASHBOARD_PASSWORD` in Render → your service → **Environment**. Use a long
  random password or passphrase (16+ characters) and enter it only there.
- Your browser shows its standard sign-in prompt. Any username works; the password
  is what counts. It is checked in constant time over Render's HTTPS.
- 10 wrong attempts from one address within 10 minutes lock that address out for
  the rest of the window. A visitor is identified by the full forwarded address
  chain, which nobody can reproduce for someone else, so nobody can lock you out
  by imitating you. The real guard is site-wide: 100 wrong attempts in 10
  minutes pause all sign-ins for the rest of the window: someone could briefly
  make the site unavailable, but they can never grind through passwords.
- `REQUIRE_PASSWORD=1` keeps the site locked (503) if the password is ever missing.
- Local runs set neither variable, so nothing changes on your PC.
- Free instances sleep after about 15 idle minutes, so the first visit takes a
  moment to wake the site.

Server-side `data/` is disposable: a restart returns to the snapshot baked into
the image, so use **Refresh FPL data** after a redeploy. Pushing, creating a
Railway service, or deploying still requires an approved task and an explicit
Overseer release decision (see `ops/WORKFLOW.md`).

- **Refresh FPL data** reads the public FPL API and rebuilds `digest.md`,
  `data/latest.json`, and the player catalog used by the dashboard.
- The Wildcard lab saves editable drafts in this browser's local storage. Drafts
  are not uploaded or synchronized. It calculates squad size, current FPL prices,
  availability flags, and the published `ep_next` sum for the immediate next
  round. It does **not** pretend that a next-round estimate is a multi-week
  forecast.
- The server uses the Python standard library. It requires no install, login, or FPL account access.
- The Decision Desk uses deterministic rules only: it pauses recommendations for stale, incomplete, warning-bearing, or post-deadline snapshots.
- `config.json` keeps the optional Jev layer disabled by default. It makes no network requests until a reviewed integration is explicitly configured.
- Research Desk renders only dated facts recorded in `data/research_packet.json`. Each source needs a title, URL, retrieval time, verification state, and at least one labeled fact. Run `run-research.ps1` to validate it locally and update `data/workflow_status.json`.
- Candidate Lens lists legal same-position replacements that meet the shown budget, team-limit, availability, minutes, xGI/90, and fixture-horizon filters. It is not a points forecast; confirm your selling price before acting.
- Run `run-refresh.ps1` for the existing public FPL refresh. It never makes FPL actions.


## Using the digest
- The Action runs at minute 17 every six hours (UTC) and commits a fresh
  `digest.md`. GitHub may delay scheduled runs, so use the manual run button
  if you need a refresh close to a deadline.
- The header identifies the **squad snapshot**, **last completed gameweek**,
  **current gameweek**, and **next deadline** separately. It is data, not a
  record of unsubmitted transfers or a guarantee of a player's starting spot.
- The availability table reproduces FPL's status, chance of playing, latest
  news text, and the time FPL last updated that news for flagged players. The
  percentage is an FPL estimate, not a medical confirmation.
- In chat, share the latest `digest.md` or its raw GitHub URL for a squad,
  captain, transfer, and bench discussion.
- Rival comparisons use only their latest public squad snapshot. They cannot
  reveal unsubmitted transfers or future captain choices.

## What the digest contains
- Manager summary: overall rank, last-GW points, points left on bench, bank,
  squad value, chips used.
- Starting XI + bench, each mapped to name/club/price/form/ownership, their
  **next fixture with difficulty (FDR)**, and captain/vice-captain markers.
- A prominent availability table for flagged squad players, including FPL's
  injury or suspension news text.
- Your #club-football rank, points gap to the leader, and a compact comparison
  of the top and nearby tracked rivals.
- The full upcoming-gameweek fixture list with FDR for both sides.

## Notes
- The FPL API occasionally changes fields between seasons — if a run errors
  after a season rollover, that's the first place to check.
- The workflow runs offline tests before it contacts FPL. Run them locally with
  `python -m unittest discover -s tests -v`.
- Everything is read-only. This never logs into your account or makes
  transfers — it only reads public data via your Team ID.
Research Scout v1
- run-research.ps1 runs the deterministic, standard-library-only Scout against the HTTPS sources declared in config.json.
- It stores schema-v2 source records with publisher, URL, retrieval times, bounded verbatim excerpts, explicit collection state, and unverified/reviewed labels. It does not infer player news, forecast points, or recommend transfers.
- The Scout is sequential, offline-readable, bounded to 10-second requests and 512 KiB responses, and retains the last successful excerpts when a later collection fails. Tests use fake responses and never call the network.
