export function confidenceLabel(value: unknown): string {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1
    ? `${Math.round(value * 100)}%`
    : '未提供'
}
