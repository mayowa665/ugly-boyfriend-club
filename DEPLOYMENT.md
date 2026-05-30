# Deployment Plan

This project is a static site. There is no server to rent and no database to run.

The free deployment plan is:

1. GitHub stores the code.
2. GitHub Actions runs once a day.
3. The action calls the football-data.org API if the API key is present.
4. The action rebuilds `state.json` with the latest scores, eliminations, bracket data, and odds.
5. The action deploys the static files to GitHub Pages.

Cloudflare is optional. Use it later only if you want a custom domain.

## What Will Be Free

- GitHub repository: free for a public repo.
- GitHub Actions: free for this tiny daily job on a public repo.
- GitHub Pages: free.
- football-data.org API key: free tier, assuming the World Cup endpoint is available to the free token.

The one thing that is usually not free is a custom domain name. You can skip that and use the GitHub Pages URL.

## What The Site Publishes

The published site only needs these files:

- `index.html`
- `styles.css`
- `app.js`
- `favicon.svg`
- `state.json`

The Python files and data files stay in the repository because GitHub Actions uses them to rebuild `state.json`.

## One-Time GitHub Setup

### 1. Create The Repository

Create a new GitHub repository called something like:

```text
uglyboyfriendclub
```

Push this project folder to the repository's `main` branch.

### 2. Enable GitHub Pages

In the GitHub repository:

```text
Settings -> Pages -> Build and deployment -> Source -> GitHub Actions
```

This matters because the workflow deploys the built site directly. Do not choose `Deploy from a branch` for this setup.

### 3. Add The API Key Secret

Get a free API token from football-data.org, then add it to GitHub:

```text
Settings -> Secrets and variables -> Actions -> New repository secret
```

Use this exact name:

```text
FOOTBALL_DATA_API_KEY
```

Paste the token as the value.

If the secret is missing, the site still builds, but it uses the pre-tournament state and will not pull live scores.

### 4. Run The Workflow Once Manually

In GitHub:

```text
Actions -> Deploy Sweepstake -> Run workflow
```

Wait for it to finish. If it succeeds, GitHub will show the Pages URL in the workflow summary and in:

```text
Settings -> Pages
```

## What Happens Every Day

The workflow runs at:

```text
06:00 UTC
```

It performs these steps:

1. Checks out the repo.
2. Installs Python dependencies from `requirements.txt`.
3. Checks the Python files compile.
4. Runs:

```powershell
python sim/build_state.py --out state.json --sims 20000
```

5. Copies the static site files into `_site`.
6. Deploys `_site` to GitHub Pages.

It does not need to commit `state.json` back to the repository each day. The deployed site gets the freshly generated `state.json` in the Pages artifact.

Note: a plain code `push` to `main` redeploys the site but **skips** the API call and deploys the
`state.json` already committed in the repo. Fresh odds come only from the daily cron and from a
manual `Run workflow`. This keeps the football-data.org free-tier quota for the runs that matter.

## How The API Update Works

The workflow passes the secret into Python as an environment variable:

```text
FOOTBALL_DATA_API_KEY
```

Then `sim/fetch_results.py` calls:

```text
https://api.football-data.org/v4/competitions/WC/matches
```

The fetched match list is used to produce:

- recent results
- eliminated teams
- current tournament phase
- knockout bracket fixtures when they exist
- refreshed entrant odds

## How To Know It Worked

Open the latest GitHub Actions run.

You want to see green checks for:

- Python setup
- dependency install
- compile check
- recompute odds
- upload Pages artifact
- deploy to GitHub Pages

Then open the Pages URL and check the `Latest` value on the site.

## If Something Breaks

### The workflow says the API key is missing

Check the secret name is exactly:

```text
FOOTBALL_DATA_API_KEY
```

### The workflow fails on `Unmapped team from results API`

The API used a team name the app does not recognize yet. Add the name to `API_NAME_TO_CODE` in `sim/fetch_results.py`.

### The workflow succeeds but the site is not updating

Check:

```text
Settings -> Pages -> Source
```

It should be set to:

```text
GitHub Actions
```

### The free API does not include World Cup data

Then the workflow will fail when it tries to call the endpoint. At that point, the next best move is to evaluate a specific free data source or scrape source, but only after checking its terms and reliability.

## Confidence Level

The repository-side setup is verifiable locally: the Python build works, `state.json` is generated, and the static site reads it.

The only part that cannot be proven from this machine is the external API token and GitHub account configuration. Once the secret is added and the first manual workflow run passes, the daily automatic update path is proven.