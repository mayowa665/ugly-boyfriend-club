import os
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any

import requests


API_NAME_TO_CODE = {
    "Algeria": "dz",
    "Argentina": "ar",
    "Australia": "au",
    "Austria": "at",
    "Belgium": "be",
    "Bosnia and Herzegovina": "ba",
    "Bosnia-Herzegovina": "ba",
    "Bosnia & Herzegovina": "ba",
    "Brazil": "br",
    "Canada": "ca",
    "Cape Verde": "cv",
    "Cabo Verde": "cv",
    "Colombia": "co",
    "Croatia": "hr",
    "Cote d'Ivoire": "ci",
    "Côte d'Ivoire": "ci",
    "Ivory Coast": "ci",
    "Curacao": "cw",
    "Curaçao": "cw",
    "Czechia": "cz",
    "Czech Republic": "cz",
    "DR Congo": "cd",
    "Congo DR": "cd",
    "Ecuador": "ec",
    "Egypt": "eg",
    "England": "gb-eng",
    "France": "fr",
    "Germany": "de",
    "Ghana": "gh",
    "Haiti": "ht",
    "Iran": "ir",
    "IR Iran": "ir",
    "Iraq": "iq",
    "Japan": "jp",
    "Jordan": "jo",
    "Korea Republic": "kr",
    "Mexico": "mx",
    "Morocco": "ma",
    "Netherlands": "nl",
    "New Zealand": "nz",
    "Norway": "no",
    "Panama": "pa",
    "Paraguay": "py",
    "Portugal": "pt",
    "Qatar": "qa",
    "Saudi Arabia": "sa",
    "Scotland": "gb-sct",
    "Senegal": "sn",
    "South Africa": "za",
    "South Korea": "kr",
    "Spain": "es",
    "Sweden": "se",
    "Switzerland": "ch",
    "Tunisia": "tn",
    "Turkey": "tr",
    "Türkiye": "tr",
    "Turkiye": "tr",
    "USA": "us",
    "United States": "us",
    "Uruguay": "uy",
    "Uzbekistan": "uz",
}


def _normalize(name: str) -> str:
    """Fold accents/case/punctuation so spelling quirks still match.

    e.g. "Bosnia-Herzegovina", "Bosnia and Herzegovina" and "Bosnia & Herzegovina"
    all collapse to the same key. Semantic aliases (USA/United States,
    Korea Republic/South Korea, Ivory Coast/Côte d'Ivoire) still need explicit
    entries in API_NAME_TO_CODE.
    """
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"\b(and|the|of|ir|dr)\b", " ", text)  # drop connectors / IR Iran / DR Congo prefixes
    return re.sub(r"[^a-z0-9]+", "", text)


_NORMALIZED_NAME_TO_CODE = {_normalize(name): code for name, code in API_NAME_TO_CODE.items()}


def _code_for(api_name: str) -> str:
    code = API_NAME_TO_CODE.get(api_name)
    if code is not None:
        return code
    code = _NORMALIZED_NAME_TO_CODE.get(_normalize(api_name))
    if code is not None:
        return code
    raise RuntimeError(f"Unmapped team from results API: {api_name}")


def fetch_fixtures() -> list[dict[str, Any]]:
    token = os.getenv("FOOTBALL_DATA_API_KEY")
    if not token:
        return []

    response = requests.get(
        "https://api.football-data.org/v4/competitions/WC/matches",
        headers={"X-Auth-Token": token},
        timeout=30,
    )
    response.raise_for_status()

    fixtures = []
    for match in response.json().get("matches", []):
        home_team = match.get("homeTeam") or {}
        away_team = match.get("awayTeam") or {}
        if not home_team.get("name") or not away_team.get("name"):
            continue

        score = match.get("score") or {}
        full_time = score.get("fullTime") or {}
        winner = score.get("winner")
        status = match.get("status", "SCHEDULED")
        utc_date = match.get("utcDate")
        stage = match.get("stage") or match.get("group") or ""
        home_code = _code_for(home_team["name"])
        away_code = _code_for(away_team["name"])

        winner_code = None
        if winner == "HOME_TEAM":
            winner_code = home_code
        elif winner == "AWAY_TEAM":
            winner_code = away_code

        fixtures.append(
            {
                "stage": normalize_stage(stage),
                "status": status,
                "home": home_code,
                "away": away_code,
                "home_score": full_time.get("home"),
                "away_score": full_time.get("away"),
                "winner": winner_code,
                "date": utc_date[:10] if utc_date else "",
                "utc_date": utc_date,
            }
        )
    return fixtures


def normalize_stage(stage: str) -> str:
    value = stage.replace("_", " ").title()
    value = value.replace("Last 32", "Round Of 32")
    value = value.replace("Last 16", "Round Of 16")
    return value


def recent_finished(fixtures: list[dict[str, Any]], names: dict[str, str], limit: int = 8) -> list[dict[str, str]]:
    finished = [
        f
        for f in fixtures
        if f.get("status") == "FINISHED"
        and f.get("home_score") is not None
        and f.get("away_score") is not None
    ]

    def sort_key(fixture: dict[str, Any]) -> datetime:
        raw = fixture.get("utc_date")
        if not raw:
            return datetime.min.replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))

    finished.sort(key=sort_key, reverse=True)
    return [
        {
            "stage": f.get("stage") or "Match",
            "home": names[f["home"]],
            "away": names[f["away"]],
            "score": f"{f['home_score']}-{f['away_score']}",
            "date": f.get("date", ""),
        }
        for f in finished[:limit]
    ]
