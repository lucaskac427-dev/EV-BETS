"""Distribution → P(actual_stat > line) conversions.

Normal: continuous stats (points, PRA, minutes).
Negative Binomial: discrete counting stats with overdispersion
(rebounds, assists, threes, blocks, steals).
"""

from scipy.stats import nbinom, norm

STAT_DISTRIBUTIONS: dict[str, str] = {
    "points": "normal",
    "pra": "normal",
    "minutes": "normal",
    "rebounds": "negative_binomial",
    "assists": "negative_binomial",
    "threes": "negative_binomial",
    "blocks": "negative_binomial",
    "steals": "negative_binomial",
}


def fair_prob_over(*, mean: float, std: float, line: float, distribution: str) -> float:
    """Return P(actual_stat > line) given the projection parameters.

    Args:
        mean: projected stat value (e.g. 24.7 points)
        std: projection standard deviation
        line: the betting line (e.g. 24.5)
        distribution: "normal" or "negative_binomial"

    Raises:
        ValueError: If distribution is unsupported or std <= 0.
    """
    if std <= 0:
        raise ValueError("std must be > 0")

    if distribution == "normal":
        # Continuity correction: P(X > line) using line + 0.5
        return float(1.0 - norm.cdf(line + 0.5, loc=mean, scale=std))

    if distribution == "negative_binomial":
        var = std**2
        # Fit NegBin to (mean, var). Requires var > mean.
        # If under-dispersed in data, clamp p near 1 (degenerate Poisson-like).
        if var > mean:
            p = mean / var
        else:
            p = 0.99
        n = mean * p / (1 - p)
        return float(1.0 - nbinom.cdf(int(line), n, p))

    raise ValueError(f"unsupported distribution: {distribution!r}")
