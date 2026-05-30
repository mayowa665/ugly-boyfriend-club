import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from sim.fetch_results import fetch_fixtures, recent_finished
from sim.model import fractional_odds
from sim.simulate import (
    GROUP_MATCHES,
    group_results,
    is_knockout_stage,
    simulate_tournament,
)


ROOT = Path(__file__).resolve().parents[1]
DISPLAY_FLOOR = 5e-5  # prototype's 0.005% floor so no-hopers show long odds, not "-"
KNOCKOUT_ROUNDS = [
    ("round_of_32", "Round Of 32"),
    ("round_of_16", "Round Of 16"),
    ("quarter_finals", "Quarter Finals"),
    ("semi_finals", "Semi Finals"),
    ("final", "Final"),
]


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="state.json")
    parser.add_argument("--sims", type=int, default=20000)
    parser.add_argument("--fixtures", help="Optional fixture JSON for tests or manual dry-runs.")
    args = parser.parse_args()

    teams = load_json(ROOT / "data" / "teams.json")
    groups = load_json(ROOT / "data" / "groups.json")
    entrants = load_json(ROOT / "data" / "entrants.json")
    names = {team["code"]: team["name"] for team in teams}

    fixtures = load_json(Path(args.fixtures)) if args.fixtures else fetch_fixtures()
    win_probs = simulate_tournament(teams, groups, fixtures, args.sims)
    eliminated = eliminated_codes(fixtures, teams, groups)
    state = build_state(teams, entrants, win_probs, eliminated, fixtures, names, args.sims)

    out_path = Path(args.out)
    out_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {out_path} with {args.sims:,} simulations.")


def display_prob(raw_prob: float, is_eliminated: bool) -> float:
    """Floor live no-hopers so they show long odds (e.g. 20000/1), not '-'.

    Eliminated teams stay at exactly 0 -> '-' / OUT.
    """
    if is_eliminated:
        return 0.0
    return raw_prob if raw_prob > 0 else DISPLAY_FLOOR


def build_state(
    teams: list[dict[str, Any]],
    entrants: list[dict[str, Any]],
    win_probs: dict[str, float],
    eliminated: set[str],
    fixtures: list[dict[str, Any]],
    names: dict[str, str],
    sims: int,
) -> dict[str, Any]:
    team_lookup = {team["code"]: team for team in teams}

    state_teams = []
    for team in teams:
        prob = display_prob(win_probs.get(team["code"], 0.0), team["code"] in eliminated)
        state_teams.append(
            {
                "code": team["code"],
                "name": team["name"],
                "conf": team["conf"],
                "p": round(prob, 6),
                "odds": fractional_odds(prob),
                "eliminated": team["code"] in eliminated,
            }
        )
    state_teams.sort(key=lambda team: (-team["p"], team["name"]))

    state_entrants = []
    for entrant in entrants:
        entrant_teams = []
        prob = 0.0
        alive_teams = 0
        for code in entrant["teams"]:
            team = team_lookup[code]
            is_eliminated = code in eliminated
            team_prob = display_prob(win_probs.get(code, 0.0), is_eliminated)
            prob += team_prob
            if not is_eliminated:
                alive_teams += 1
            entrant_teams.append(
                {
                    "code": code,
                    "name": team["name"],
                    "conf": team["conf"],
                    "p": round(team_prob, 6),
                    "eliminated": is_eliminated,
                }
            )
        state_entrants.append(
            {
                "name": entrant["name"],
                "prob": round(prob, 6),
                "odds": fractional_odds(prob),
                "alive_teams": alive_teams,
                "teams": entrant_teams,
            }
        )
    state_entrants.sort(key=lambda entrant: (-entrant["prob"], entrant["name"]))

    return {
        "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "phase": derive_phase(fixtures),
        "sims": sims,
        "entrants": state_entrants,
        "teams": state_teams,
        "recent_results": recent_finished(fixtures, names),
        "knockout_bracket": knockout_bracket(fixtures, names),
    }


def derive_phase(fixtures: list[dict[str, Any]]) -> str:
    if not fixtures:
        return "pre_tournament"

    finished = [fixture for fixture in fixtures if fixture.get("status") == "FINISHED"]
    if len(finished) == len(fixtures):
        return "complete"

    live_statuses = {"IN_PLAY", "LIVE", "PAUSED", "EXTRA_TIME", "PENALTY_SHOOTOUT"}
    live = [fixture for fixture in fixtures if fixture.get("status") in live_statuses]
    if not finished and not live:
        return "pre_tournament"

    stage_fixtures = live or next_unfinished_fixtures(fixtures) or finished
    return phase_from_stage(" ".join(str(f.get("stage", "")) for f in stage_fixtures))


def next_unfinished_fixtures(fixtures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unfinished = [fixture for fixture in fixtures if fixture.get("status") != "FINISHED"]
    if not unfinished:
        return []

    def sort_key(fixture: dict[str, Any]) -> str:
        return fixture.get("utc_date") or fixture.get("date") or "9999-99-99"

    next_fixture = min(unfinished, key=sort_key)
    next_stage = next_fixture.get("stage")
    return [fixture for fixture in unfinished if fixture.get("stage") == next_stage]


def phase_from_stage(stage: str) -> str:
    stage_text = stage.replace("_", " ").lower()
    return knockout_stage_key(stage_text) or "group_stage"


def knockout_stage_key(stage: str) -> str | None:
    stage_text = stage.replace("_", " ").lower()
    if "semi" in stage_text:
        return "semi_finals"
    if "quarter" in stage_text:
        return "quarter_finals"
    if "round of 16" in stage_text or "last 16" in stage_text:
        return "round_of_16"
    if "round of 32" in stage_text or "last 32" in stage_text:
        return "round_of_32"
    if "final" in stage_text:
        return "final"
    return None


def knockout_bracket(fixtures: list[dict[str, Any]], names: dict[str, str]) -> list[dict[str, Any]]:
    rounds: dict[str, list[dict[str, Any]]] = {key: [] for key, _ in KNOCKOUT_ROUNDS}

    for fixture in sorted(fixtures, key=fixture_sort_key):
        stage_key = knockout_stage_key(str(fixture.get("stage", "")))
        if stage_key not in rounds:
            continue
        rounds[stage_key].append(bracket_match(fixture, names))

    return [
        {"key": key, "stage": label, "matches": rounds[key]}
        for key, label in KNOCKOUT_ROUNDS
        if rounds[key]
    ]


def fixture_sort_key(fixture: dict[str, Any]) -> str:
    return fixture.get("utc_date") or fixture.get("date") or "9999-99-99"


def bracket_match(fixture: dict[str, Any], names: dict[str, str]) -> dict[str, Any]:
    home = fixture.get("home")
    away = fixture.get("away")
    return {
        "date": fixture.get("date", ""),
        "status": fixture.get("status", "SCHEDULED"),
        "home_code": home,
        "away_code": away,
        "home_name": names.get(home, "TBD") if home else "TBD",
        "away_name": names.get(away, "TBD") if away else "TBD",
        "home_score": fixture.get("home_score"),
        "away_score": fixture.get("away_score"),
        "winner_code": fixture_winner(fixture),
    }


def fixture_winner(fixture: dict[str, Any]) -> str | None:
    if fixture.get("winner"):
        return fixture["winner"]

    home_score = fixture.get("home_score")
    away_score = fixture.get("away_score")
    if home_score is None or away_score is None:
        return None
    if home_score > away_score:
        return fixture.get("home")
    if away_score > home_score:
        return fixture.get("away")
    return None


def eliminated_codes(
    fixtures: list[dict[str, Any]],
    teams: list[dict[str, Any]],
    groups: dict[str, list[str]],
) -> set[str]:
    """Teams that can no longer win the cup, derived from real results only.

    A team is out if it (a) lost a finished knockout match, (b) finished bottom of a
    fully-played group, or (c) is one of the four non-advancing third-placed teams
    once every group is complete. No team is flagged on simulated probability alone.
    """
    if not fixtures:
        return set()

    elo = {team["code"]: team["elo"] for team in teams}
    group_played = group_results(fixtures)
    eliminated: set[str] = set()

    # (a) Knockout losers.
    for fixture in fixtures:
        if fixture.get("status") != "FINISHED" or not is_knockout_stage(fixture.get("stage")):
            continue
        winner = fixture.get("winner")
        home, away = fixture.get("home"), fixture.get("away")
        if winner in (home, away) and winner:
            eliminated.add(away if winner == home else home)

    # (b) Bottom of any completed group; collect thirds for (c).
    completed_thirds = []
    completed_count = 0
    for members in groups.values():
        standings = _completed_group(members, group_played, elo)
        if standings is None:
            continue
        completed_count += 1
        ranked, stats = standings
        eliminated.add(ranked[3])
        completed_thirds.append((ranked[2], stats[ranked[2]]))

    # (c) Once all groups are done, the four weakest thirds are out too.
    if completed_count == len(groups):
        completed_thirds.sort(
            key=lambda row: (-row[1]["points"], -row[1]["gd"], -row[1]["gf"], -elo[row[0]])
        )
        for team, _ in completed_thirds[8:]:
            eliminated.add(team)

    return eliminated


def _completed_group(
    members: list[str],
    group_played: dict[frozenset[str], dict[str, Any]],
    elo: dict[str, float],
) -> tuple[list[str], dict[str, dict[str, int]]] | None:
    """Final standings for a group whose six games are all finished, else None."""
    stats = {team: {"points": 0, "gd": 0, "gf": 0} for team in members}
    for left, right in GROUP_MATCHES:
        fixed = group_played.get(frozenset((members[left], members[right])))
        if not fixed:
            return None
        home, away = members[left], members[right]
        hg, ag = fixed["scores"][home], fixed["scores"][away]
        stats[home]["gd"] += hg - ag
        stats[away]["gd"] += ag - hg
        stats[home]["gf"] += hg
        stats[away]["gf"] += ag
        if fixed["winner"] == home:
            stats[home]["points"] += 3
        elif fixed["winner"] == away:
            stats[away]["points"] += 3
        else:
            stats[home]["points"] += 1
            stats[away]["points"] += 1
    ranked = sorted(
        members,
        key=lambda t: (-stats[t]["points"], -stats[t]["gd"], -stats[t]["gf"], -elo[t]),
    )
    return ranked, stats


if __name__ == "__main__":
    main()
