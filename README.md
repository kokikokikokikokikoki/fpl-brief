# FPL Brief — auto data pipeline

Pulls your Fantasy Premier League squad, stats and upcoming fixtures from the
public FPL API and writes `digest.md`. Claude reads that digest each week and
layers on the YouTuber consensus + captaincy/transfer verdict.

**You never paste data again** — the GitHub Action refreshes `digest.md`
automatically before each deadline, and Claude reads it straight from GitHub.

## Repo layout
```
your-repo/
├── fetch_fpl.py                  # the fetcher (no dependencies, stdlib only)
├── digest.md                     # generated output — Claude reads this
├── README.md
└── .github/workflows/
    └── fpl-digest.yml            # weekly cron + manual run
```

## One-time setup (~10 min)
1. Create a **public** GitHub repo (public so Claude can read the raw file).
   If you'd rather keep it private, that's fine too — just paste `digest.md`
   into chat each week instead.
2. Add `fetch_fpl.py` and `README.md` at the root.
3. Add `fpl-digest.yml` at `.github/workflows/fpl-digest.yml`.
4. Your Team ID (`6572775`) is already set in both files. To change it, edit
   `TEAM_ID` in `fetch_fpl.py` and `FPL_TEAM_ID` in the workflow.
5. Go to the repo's **Actions** tab → enable workflows → click
   **FPL Digest → Run workflow** once to generate the first `digest.md`.

## Run it locally (optional)
```bash
python fetch_fpl.py          # writes digest.md
FPL_TEAM_ID=1234567 python fetch_fpl.py   # any other team
```

## Weekly flow
- The Action runs every **Friday 09:00 UTC** and commits a fresh `digest.md`.
  (Change the `cron` line if deadlines shift — e.g. Thursday double GWs.)
- In chat, just say **"run my FPL brief"**. Claude reads the latest digest at
  `raw.githubusercontent.com/<you>/<repo>/main/digest.md`, pulls the current
  creator consensus, and gives you the captain / transfer / bench verdict.

## What the digest contains
- Manager summary: overall rank, last-GW points, points left on bench, bank,
  squad value, chips used.
- Starting XI + bench, each mapped to name/club/price/form/ownership, their
  **next fixture with difficulty (FDR)**, and any injury/suspension flag.
- The full upcoming-gameweek fixture list with FDR for both sides.

## Notes
- The FPL API occasionally changes fields between seasons — if a run errors
  after a season rollover, that's the first place to check.
- Everything is read-only. This never logs into your account or makes
  transfers — it only reads public data via your Team ID.
