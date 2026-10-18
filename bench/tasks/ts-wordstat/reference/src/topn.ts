export function topN(counts: Map<string, number>, n: number): [string, number][] {
  if (n <= 0) return [];
  const cmp = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0);
  return [...counts.entries()].sort((a, b) => b[1] - a[1] || cmp(a[0], b[0])).slice(0, n);
}
