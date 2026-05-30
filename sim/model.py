import math
from typing import Optional

import numpy as np


def match_lambdas(home_elo: float, away_elo: float) -> tuple[float, float]:
    diff = home_elo - away_elo
    lam_home = 1.35 * (10 ** (diff / 900))
    lam_away = 1.35 * (10 ** (-diff / 900))
    return min(lam_home, 5.5), min(lam_away, 5.5)


def shootout_probability(home_elo: float, away_elo: float) -> float:
    return 1 / (1 + 10 ** ((away_elo - home_elo) / 400))


def simulate_match(
    home: str,
    away: str,
    elo: dict[str, float],
    rng: np.random.Generator,
    knockout: bool = False,
) -> tuple[int, int, Optional[str]]:
    lam_home, lam_away = match_lambdas(elo[home], elo[away])
    home_goals = int(rng.poisson(lam_home))
    away_goals = int(rng.poisson(lam_away))

    if home_goals > away_goals:
        return home_goals, away_goals, home
    if away_goals > home_goals:
        return home_goals, away_goals, away
    if knockout:
        p_home = shootout_probability(elo[home], elo[away])
        return home_goals, away_goals, home if rng.random() < p_home else away
    return home_goals, away_goals, None


def fractional_odds(probability: float) -> str:
    if probability <= 0:
        return "-"

    p = probability
    against = (1 - p) / p
    if against >= 500:
        return f"{round(against / 100) * 100}/1"
    if against >= 50:
        return f"{round(against / 5) * 5}/1"
    if against >= 10:
        return f"{round(against)}/1"
    if against >= 4:
        halved = round(against * 2)
        return f"{halved // 2}/1" if halved % 2 == 0 else f"{halved}/2"
    if against >= 1:
        fracs = [
            (11, 10),
            (6, 5),
            (5, 4),
            (11, 8),
            (6, 4),
            (13, 8),
            (7, 4),
            (15, 8),
            (2, 1),
            (9, 4),
            (5, 2),
            (11, 4),
            (3, 1),
            (10, 3),
            (7, 2),
            (4, 1),
        ]
        num, den = min(fracs, key=lambda f: abs((f[0] / f[1]) - against))
        return f"{num}/{den}"

    return f"1/{math.floor((p / (1 - p)) + 0.5 + 1e-9)}"
