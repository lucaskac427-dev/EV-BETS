"""Shared helpers for player-prop scrapers: player/stat parsing + synthetic
ticker construction. All sharp-book scrapers emit the same synthetic ticker so
the pipeline can join quotes across books.

The synth ticker is sport-namespaced (SYN-NBA-..., SYN-SOCCER-...) so the
same surname in different sports never collide. Player names are normalized
through Unicode NFKD so accented spellings (Vinícius Júnior) join their
ASCII counterparts (Vinicius Junior) automatically.
"""

import re
import unicodedata


def parse_player_stat_description(desc: str) -> tuple[str | None, str | None]:
    """'LeBron James (Total Points)' -> ('LeBron James', 'points')."""
    match = re.match(r"^(.+?)\s*\(Total\s+(\w+)\)$", desc, re.IGNORECASE)
    if not match:
        return None, None
    return match.group(1).strip(), match.group(2).lower()


def _normalize_name(name: str) -> str:
    """NFKD strip accents -> letters only -> upper. Vinícius Júnior == Vinicius Junior."""
    if not name:
        return ""
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_only = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"[^A-Za-z]+", "", ascii_only).upper()


def synthesize_ticker(sport: str, player: str, stat: str | None, line: float) -> str:
    """Canonical synth ticker: SYN-{SPORT}-{playerslug}-{STAT}-{line}.
    Used to join quotes across books in the same sport."""
    slug = _normalize_name(player)
    return f"SYN-{sport.upper()}-{slug}-{stat.upper() if stat else 'UNK'}-{line}"


def synthesize_kalshi_ticker(player: str, stat: str | None, line: float) -> str:
    """NBA-defaulted alias for backwards compatibility with the original
    NBA-only call sites. New code should use synthesize_ticker(sport, ...)."""
    return synthesize_ticker("NBA", player, stat, line)
