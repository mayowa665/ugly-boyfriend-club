# Ugly Boyfriend Club World Cup Sweepstake

A static GitHub Pages site for the 2026 sweepstake. The page reads `state.json`; a GitHub Actions workflow rebuilds the odds once a day and deploys the updated site to GitHub Pages.

## Local use

```powershell
pip install -r requirements.txt
python sim/build_state.py --out state.json --sims 20000
python -m http.server 8080
```

Open `http://localhost:8080`.

Without `FOOTBALL_DATA_API_KEY`, the builder uses the pre-tournament state. In GitHub Actions, add the free football-data.org key as the repository secret `FOOTBALL_DATA_API_KEY`.

## Deploy

Use the GitHub Pages workflow in `.github/workflows/update.yml`. Full setup notes are in `DEPLOYMENT.md`.
