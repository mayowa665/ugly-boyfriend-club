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
    "Bosnia-H.": "ba",
    "Brazil": "br",
    "Canada": "ca",
    "Cape Verde": "cv",
    "Cabo Verde": "cv",
    "Cape Verde Islands": "cv",
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
    text = re.sub(r"\b(and|the|of|ir|dr|islands?)\b", " ", text)  # drop connectors / IR Iran / DR Congo / "Islands"
    return re.sub(r"[^a-z0-9]+", "", text)


_NORMALIZED_NAME_TO_CODE = {_normalize(name): code for name, code in API_NAME_TO_CODE.items()}

# FIFA 3-letter codes (the API's `tla` field) for all 48 finalists. This is the
# most stable identifier the feed provides, so it's the backstop when the display
# name is unexpected (e.g. "Cape Verde Islands").
TLA_TO_CODE = {
    "ESP": "es", "ARG": "ar", "FRA": "fr", "ENG": "gb-eng", "BRA": "br",
    "POR": "pt", "NED": "nl", "GER": "de", "CRO": "hr", "BEL": "be",
    "COL": "co", "URY": "uy", "SUI": "ch", "MAR": "ma", "USA": "us",
    "MEX": "mx", "SEN": "sn", "JPN": "jp", "KOR": "kr", "AUT": "at",
    "ECU": "ec", "TUR": "tr", "IRN": "ir", "SWE": "se", "NOR": "no",
    "AUS": "au", "PAR": "py", "CIV": "ci", "ALG": "dz", "SCO": "gb-sct",
    "CZE": "cz", "EGY": "eg", "CAN": "ca", "TUN": "tn", "BIH": "ba",
    "GHA": "gh", "KSA": "sa", "RSA": "za", "COD": "cd", "QAT": "qa",
    "CPV": "cv", "PAN": "pa", "UZB": "uz", "JOR": "jo", "IRQ": "iq",
    "HAI": "ht", "NZL": "nz", "CUW": "cw",
}


def _code_for(api_name: str) -> str | None:
    """Resolve a single name string (exact, then accent/punctuation-normalized)."""
    if not api_name:
        return None
    code = API_NAME_TO_CODE.get(api_name)
    if code is not None:
        return code
    return _NORMALIZED_NAME_TO_CODE.get(_normalize(api_name))


def resolve_team(team: dict[str, Any]) -> str:
    """Map an API team object to our code using every identifier it provides.

    Tries name, then shortName, then the FIFA `tla` code. Only fails loudly if all
    three are unrecognised, which for a fixed 48-team field should never happen.
    """
    for key in ("name", "shortName"):
        code = _code_for(team.get(key) or "")
        if code is not None:
            return code
    tla = (team.get("tla") or "").upper()
    if tla in TLA_TO_CODE:
        return TLA_TO_CODE[tla]
    raise RuntimeError(
        f"Unmapped team from results API: name={team.get('name')!r} "
        f"shortName={team.get('shortName')!r} tla={team.get('tla')!r}"
    )


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
        home_code = resolve_team(home_team)
        away_code = resolve_team(away_team)

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
