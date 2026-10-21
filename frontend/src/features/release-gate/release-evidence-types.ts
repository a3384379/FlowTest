import type { ReleaseReason } from './release-gate-service'

export type ReleaseEvidenceKind = ReleaseReason['evidence_type']

export const releaseEvidenceLabels: Readonly<Record<ReleaseEvidenceKind, string>> = {
  quality_gate: '质量运行',
  contract_compatibility: '契约判断',
  impact: '影响分析',
  release_risk: '发布风险',
  performance: '性能运行',
  runner: 'Runner任务',
}
