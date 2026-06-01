/**
 * Probability ↔ American-odds conversions.
 *
 * American odds:
 *   p >= 0.5  ->  -100 / (decimal - 1)   (e.g. p=0.55 -> -122)
 *   p < 0.5   ->  +100 * (decimal - 1)   (e.g. p=0.47 -> +112)
 */

export function probToDecimal(p: number): number {
  if (p <= 0 || p >= 1) return NaN;
  return 1 / p;
}

export function probToAmerican(p: number): string {
  if (p <= 0 || p >= 1) return "—";
  const decimal = 1 / p;
  if (decimal >= 2) {
    return "+" + Math.round((decimal - 1) * 100);
  }
  return "-" + Math.round(100 / (decimal - 1));
}

/**
 * True expected value of a single bet given fair_prob and the effective
 * decimal odds at the book you're betting at. Matches the standard
 * sports-betting formula:
 *
 *   EV = fair × decimal − 1
 *     = (fair / breakeven) − 1   (when decimal = 1/breakeven)
 */
export function trueEvPct(fairProb: number, breakeven: number): number {
  if (breakeven <= 0 || breakeven >= 1) return 0;
  return fairProb / breakeven - 1;
}
