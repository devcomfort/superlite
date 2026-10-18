/** Round to 6 decimals, drop trailing zeros and a trailing '.', never print -0. */
export function fmtNumber(x: number): string {
  return String(Number(x.toFixed(6)) + 0);
}
