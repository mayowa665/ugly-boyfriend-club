"""Conditional Monte Carlo for the 2026 World Cup.

The bracket is a *fixed tree* taken from FIFA's published 2026 schedule (matches
73-104). This is what lets the simulation condition on real knockout results: a
team that has actually been knocked out occupies no slot it can win from, so it
ends with P(win) = 0.

Two bracket-construction modes:

* **Projection (pre-knockout):** group winners / runners-up / best-thirds are slotted
  into the official R32 template every iteration. Used pre-tournament and during the
  group stage, where the bracket is still uncertain.
* **Anchored (live knockout):** once the API publishes the real Round-of-32 fixtures,
  the leaves are taken directly from reality and aligned to the fixed tree, so real
  FINISHED results are applied exactly and the rest are simulated forward.
"""

from collections import Counter
from typing import Any, Optional

import numpy as np

from .model import simulate_match


# Round-robin order within a group of 4 (indices into the group list).
GROUP_MATCHES = [(0, 1), (2, 3), (0, 2), (1, 3), (0, 3), (1, 2)]


def _third(groups: str) -> tuple[str, frozenset[str]]:
    return ("3", frozenset(groups))


# Official 2026 Round-of-32 template: match number -> (home slot, away slot).
# Slot tokens: ("W", "A")=winner of A, ("R", "A")=runner-up of A,
# ("3", {groups})=best third-placed team from one of those groups.
R32_LEAVES: dict[int, tuple[tuple[str, Any], tuple[str, Any]]] = {
    73: (("R", "A"), ("R", "B")),
    74: (("W", "E"), _third("ABCDF")),
    75: (("W", "F"), ("R", "C")),
    76: (("W", "C"), ("R", "F")),
    77: (("W", "I"), _third("CDFGH")),
    78: (("R", "E"), ("R", "I")),
    79: (("W", "A"), _third("CEFHI")),
    80: (("W", "L"), _third("EHIJK")),
    81: (("W", "D"), _third("BEFIJ")),
    82: (("W", "G"), _third("AEHIJ")),
    83: (("R", "K"), ("R", "L")),
    84: (("W", "H"), ("R", "J")),
    85: (("W", "B"), _third("EFGIJ")),
    86: (("W", "J"), ("R", "H")),
    87: (("W", "K"), _third("DEIJL")),
    88: (("R", "D"), ("R", "G")),
}

# Third-placed slots in fixed order, each with its allowed source groups.
THIRD_SLOTS: list[tuple[int, frozenset[str]]] = [
    (m, leaf[1][1]) for m, leaf in R32_LEAVES.items() if leaf[1][0] == "3"
]

# Internal matches: match number -> (child match a, child match b).
FEED: dict[int, tuple[int, int]] = {
    89: (74, 77), 90: (73, 75), 91: (76, 78), 92: (79, 80),
    93: (83, 84), 94: (81, 82), 95: (86, 88), 96: (85, 87),
    97: (89, 90), 98: (93, 94), 99: (91, 92), 100: (95, 96),
    101: (97, 98), 102: (99, 100),
    104: (101, 102),
}
FINAL_MATCH = 104
R32_MATCHES = list(R32_LEAVES.keys())
INTERNAL_MATCHES = list(FEED.keys())  # already in dependency order

_KNOCKOUT_KEYS = ("round of 32", "last 32", "round of 16", "last 16",
                  "quarter", "semi", "final")


def is_knockout_stage(stage: Any) -> bool:
    text = str(stage or "").replace("_", " ").lower()
    return any(key in text for key in _KNOCKOUT_KEYS)


def simulate_tournament(
    teams: list[dict[str, Any]],
    groups: dict[str, list[str]],
    fixtures: list[dict[str, Any]],
    sims: int,
    seed: int = 42,
) -> dict[str, float]:
    codes = [team["code"] for team in teams]
    elo = {team["code"]: team["elo"] for team in teams}
    team_group = {code: letter for letter, members in groups.items() for code in members}

    group_played = group_results(fixtures)
    knockout = build_knockout_real(fixtures, groups, elo, group_played)

    rng = np.random.default_rng(seed)
    thirds_cache: dict[frozenset[str], dict[int, str]] = {}
    winners: Counter = Counter()
    for _ in range(sims):
        winners[run_one(groups, elo, team_group, group_played, knockout, rng, thirds_cache)] += 1

    return {code: winners[code] / sims for code in codes}


def run_one(
    groups: dict[str, list[str]],
    elo: dict[str, float],
    team_group: dict[str, str],
    group_played: dict[frozenset[str], dict[str, Any]],
    knockout: Optional[dict[str, Any]],
    rng: np.random.Generator,
    thirds_cache: dict[frozenset[str], dict[int, str]],
) -> str:
    if knockout is not None:
        # Anchored mode: leaves are the real R32 matchups; only play the bracket.
        return play_bracket(knockout["leaves"], knockout["played"], elo, rng)

    # Projection mode: resolve groups, then slot into the official template.
    winners: dict[str, str] = {}
    runners: dict[str, str] = {}
    third_rows = []
    for letter, members in groups.items():
        ranked, stats = simulate_group(members, elo, group_played, rng)
        winners[letter] = ranked[0]
        runners[letter] = ranked[1]
        third_rows.append((letter, ranked[2], stats[ranked[2]]))

    third_rows.sort(key=lambda row: (-row[2]["points"], -row[2]["gd"], -row[2]["gf"], rng.random()))
    advancing = third_rows[:8]
    third_team = {row[0]: row[1] for row in advancing}
    qualified_groups = frozenset(third_team)

    slot_assign = thirds_cache.get(qualified_groups)
    if slot_assign is None:
        slot_assign = assign_thirds(qualified_groups)
        thirds_cache[qualified_groups] = slot_assign

    leaves = {}
    for match, (home_slot, away_slot) in R32_LEAVES.items():
        leaves[match] = (
            _resolve_slot(home_slot, winners, runners, third_team, slot_assign, match),
            _resolve_slot(away_slot, winners, runners, third_team, slot_assign, match),
        )
    return play_bracket(leaves, {}, elo, rng)


def _resolve_slot(slot, winners, runners, third_team, slot_assign, match):
    kind, value = slot
    if kind == "W":
        return winners[value]
    if kind == "R":
        return runners[value]
    return third_team[slot_assign[match]]


def play_bracket(
    leaves: dict[int, tuple[str, str]],
    played: dict[frozenset[str], str],
    elo: dict[str, float],
    rng: np.random.Generator,
) -> str:
    results: dict[int, str] = {}
    for match in R32_MATCHES:
        home, away = leaves[match]
        results[match] = _decide(home, away, played, elo, rng)
    for match in INTERNAL_MATCHES:
        a, b = FEED[match]
        results[match] = _decide(results[a], results[b], played, elo, rng)
    return results[FINAL_MATCH]


def _decide(home, away, played, elo, rng) -> str:
    real = played.get(frozenset((home, away)))
    if real in (home, away):
        return real
    _, _, winner = simulate_match(home, away, elo, rng, knockout=True)
    return winner


def assign_thirds(qualified: frozenset[str]) -> dict[int, str]:
    """Match the 8 advancing third-placed groups to their allowed R32 slots.

    Any valid 8-of-12 combination has a perfect matching against the official slot
    constraints; we find a deterministic one via backtracking (most-constrained slot
    first). Falls back gracefully if a combination is ever unmatchable.
    """
    slots = [(match, qualified & allowed) for match, allowed in THIRD_SLOTS]
    slots.sort(key=lambda s: len(s[1]))
    assignment: dict[int, str] = {}
    used: set[str] = set()

    def solve(index: int) -> bool:
        if index == len(slots):
            return True
        match, candidates = slots[index]
        for group in sorted(candidates):
            if group in used:
                continue
            used.add(group)
            assignment[match] = group
            if solve(index + 1):
                return True
            used.discard(group)
            del assignment[match]
        return False

    if solve(0):
        return assignment

    # Fallback: assign remaining groups arbitrarily (should not happen with a valid draw).
    leftover = sorted(qualified - used)
    for match, _ in THIRD_SLOTS:
        if match not in assignment and leftover:
            assignment[match] = leftover.pop()
    return assignment


def simulate_group(
    members: list[str],
    elo: dict[str, float],
    group_played: dict[frozenset[str], dict[str, Any]],
    rng: np.random.Generator,
) -> tuple[list[str], dict[str, dict[str, int]]]:
    stats = {team: {"points": 0, "gd": 0, "gf": 0} for team in members}
    for left, right in GROUP_MATCHES:
        home, away = members[left], members[right]
        fixed = group_played.get(frozenset((home, away)))
        if fixed:
            home_goals = fixed["scores"][home]
            away_goals = fixed["scores"][away]
            winner = fixed["winner"]
        else:
            home_goals, away_goals, winner = simulate_match(home, away, elo, rng)
        _apply(stats, home, away, home_goals, away_goals, winner)

    ranked = sorted(
        members,
        key=lambda team: (-stats[team]["points"], -stats[team]["gd"], -stats[team]["gf"], rng.random()),
    )
    return ranked, stats


def _apply(stats, home, away, home_goals, away_goals, winner) -> None:
    stats[home]["gd"] += home_goals - away_goals
    stats[away]["gd"] += away_goals - home_goals
    stats[home]["gf"] += home_goals
    stats[away]["gf"] += away_goals
    if winner == home:
        stats[home]["points"] += 3
    elif winner == away:
        stats[away]["points"] += 3
    else:
        stats[home]["points"] += 1
        stats[away]["points"] += 1


def group_results(fixtures: list[dict[str, Any]]) -> dict[frozenset[str], dict[str, Any]]:
    """Finished group-stage games only, keyed by team pair."""
    played: dict[frozenset[str], dict[str, Any]] = {}
    for fixture in fixtures:
        if fixture.get("status") != "FINISHED" or is_knockout_stage(fixture.get("stage")):
            continue
        if fixture.get("home_score") is None or fixture.get("away_score") is None:
            continue
        home, away = fixture["home"], fixture["away"]
        home_score, away_score = int(fixture["home_score"]), int(fixture["away_score"])
        if home_score > away_score:
            winner = home
        elif away_score > home_score:
            winner = away
        else:
            winner = fixture.get("winner")
        played[frozenset((home, away))] = {
            "scores": {home: home_score, away: away_score},
            "winner": winner,
        }
    return played


def knockout_results(fixtures: list[dict[str, Any]]) -> dict[frozenset[str], str]:
    """Finished knockout games only, keyed by team pair -> winner code."""
    played: dict[frozenset[str], str] = {}
    for fixture in fixtures:
        if fixture.get("status") != "FINISHED" or not is_knockout_stage(fixture.get("stage")):
            continue
        winner = fixture.get("winner")
        if winner in (fixture.get("home"), fixture.get("away")) and winner:
            played[frozenset((fixture["home"], fixture["away"]))] = winner
    return played


def final_group_positions(
    groups: dict[str, list[str]],
    group_played: dict[frozenset[str], dict[str, Any]],
    elo: dict[str, float],
) -> Optional[dict[str, tuple[str, int]]]:
    """Deterministic 1..4 standings for *fully played* groups (Elo breaks ties).

    Returns None unless every group has all six games finished.
    """
    positions: dict[str, tuple[str, int]] = {}
    for letter, members in groups.items():
        stats = {team: {"points": 0, "gd": 0, "gf": 0} for team in members}
        played_count = 0
        for left, right in GROUP_MATCHES:
            home, away = members[left], members[right]
            fixed = group_played.get(frozenset((home, away)))
            if not fixed:
                return None
            played_count += 1
            _apply(stats, home, away, fixed["scores"][home], fixed["scores"][away], fixed["winner"])
        if played_count < 6:
            return None
        ranked = sorted(
            members,
            key=lambda t: (-stats[t]["points"], -stats[t]["gd"], -stats[t]["gf"], -elo[t]),
        )
        for pos, team in enumerate(ranked, start=1):
            positions[team] = (letter, pos)
    return positions


def build_knockout_real(
    fixtures: list[dict[str, Any]],
    groups: dict[str, list[str]],
    elo: dict[str, float],
    group_played: dict[frozenset[str], dict[str, Any]],
) -> Optional[dict[str, Any]]:
    """Anchor the bracket to reality once the real R32 fixtures are published.

    Returns ``{"leaves": {...}, "played": {...}}`` or ``None`` to fall back to the
    projection bracket (pre-knockout, or if the data is incomplete/ambiguous).
    """
    r32 = [
        f for f in fixtures
        if "round of 32" in str(f.get("stage", "")).replace("_", " ").lower()
        or "last 32" in str(f.get("stage", "")).replace("_", " ").lower()
    ]
    if len(r32) != len(R32_LEAVES):
        return None
    if any(not f.get("home") or not f.get("away") for f in r32):
        return None

    positions = final_group_positions(groups, group_played, elo)
    if positions is None:
        return None

    # Map every winner/runner slot to the concrete team that fills it.
    slot_team: dict[tuple[str, str], str] = {}
    for team, (letter, pos) in positions.items():
        if pos == 1:
            slot_team[("W", letter)] = team
        elif pos == 2:
            slot_team[("R", letter)] = team

    # For each tree leaf, which concrete team sits on the non-third side(s).
    concrete_to_leaf: dict[str, tuple[int, str]] = {}
    for match, (home_slot, away_slot) in R32_LEAVES.items():
        if home_slot[0] in ("W", "R"):
            concrete_to_leaf[slot_team[home_slot]] = (match, "home")
        if away_slot[0] in ("W", "R"):
            concrete_to_leaf[slot_team[away_slot]] = (match, "away")

    leaves: dict[int, tuple[Optional[str], Optional[str]]] = {m: [None, None] for m in R32_LEAVES}
    for fixture in r32:
        a, b = fixture["home"], fixture["away"]
        anchor = a if a in concrete_to_leaf else (b if b in concrete_to_leaf else None)
        if anchor is None:
            return None  # ambiguous; fall back to projection
        match, side = concrete_to_leaf[anchor]
        other = b if anchor == a else a
        slots = list(leaves[match])
        if side == "home":
            slots[0], slots[1] = anchor, other
        else:
            slots[0], slots[1] = other, anchor
        leaves[match] = slots

    if any(home is None or away is None for home, away in leaves.values()):
        return None

    return {
        "leaves": {m: (h, a) for m, (h, a) in leaves.items()},
        "played": knockout_results(fixtures),
    }
