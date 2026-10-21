type CoverageDisplay = { label: string; percent: number | null }

export function contractCoverage(
  value: unknown,
  count: unknown,
  available: boolean,
): CoverageDisplay {
  if (!available) return { label: '未提供', percent: null }
  if (count === 0) return { label: '无可评估项', percent: null }
  if (typeof count !== 'number' || !Number.isFinite(count) || count < 0) {
    return { label: '未提供', percent: null }
  }
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0 || value > 100) {
    return { label: '未提供', percent: null }
  }
  return { label: `${value}%`, percent: value }
}
