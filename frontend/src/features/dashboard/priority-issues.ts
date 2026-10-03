import type { ImpactRunSummary } from '../impact/impact-service'
import { projectPath } from '../projects/project-routing'
import type { ReleaseDecision } from '../release-gate/release-gate-service'
import type { FlakyRecord, ReleaseRiskDetail } from '../quality/quality-service'
import { reportExecutionPath } from '../workflows/execution-navigation'
import type { Page, RecentExecution } from '../../lib/api'

export type PriorityIssue = {
  id: string
  rank: number
  weight: number
  category: string
  title: string
  description: string
  scope: string
  href: string
  action: string
}

type Input = {
  projectId: string
  decision?: ReleaseDecision
  risk?: ReleaseRiskDetail
  impact?: ImpactRunSummary
  recent?: Page<RecentExecution>
  flaky?: Page<FlakyRecord>
}

export function priorityIssues(input: Input): PriorityIssue[] {
  return [
    ...blockedRelease(input.projectId, input.decision),
    ...failureClusters(input.projectId, input.risk),
    ...failedRecentRuns(input.projectId, input.recent),
    ...coverageGaps(input.projectId, input.impact),
    ...flakyAssets(input.projectId, input.flaky),
  ].sort(
    (left, right) =>
      left.rank - right.rank || right.weight - left.weight || left.id.localeCompare(right.id),
  )
}

function blockedRelease(projectId: string, decision?: ReleaseDecision): PriorityIssue[] {
  if (!decision || decision.status !== 'block') return []
  return [
    {
      id: `release:${decision.id}`,
      rank: 0,
      weight: 0,
      category: '发布阻断',
      title: `候选 ${decision.candidate_ref} 被门禁阻断`,
      description:
        decision.reasons
          .filter((reason) => reason.status === 'blocked')
          .map((reason) => reason.message)
          .join('；') || '查看冻结判断中的阻断证据',
      scope: `最新判断 ${decision.id} · 候选 ${decision.candidate_ref} · ${decision.created_at}`,
      href: projectPath(projectId, 'release'),
      action: '打开发布门禁',
    },
  ]
}

function failureClusters(projectId: string, risk?: ReleaseRiskDetail): PriorityIssue[] {
  if (!risk) return []
  return risk.failure_clusters.map((cluster) => {
    const executionId = cluster.sample_execution_ids[0]
    return {
      id: `cluster:${cluster.id}`,
      rank: 1,
      weight: cluster.occurrence_count,
      category: '冻结失败簇',
      title: cluster.title,
      description: `${cluster.occurrence_count} 次发生 · 置信度 ${Math.round(cluster.confidence * 100)}% · ${cluster.recommendation}`,
      scope: `风险快照 ${risk.id} · ${risk.window_started_at} 至 ${risk.window_ended_at}`,
      href: executionId
        ? reportExecutionPath(projectId, { executionId })
        : projectPath(projectId, 'quality'),
      action: executionId ? '查看样本执行报告' : '打开质量中心',
    }
  })
}

function failedRecentRuns(projectId: string, page?: Page<RecentExecution>): PriorityIssue[] {
  if (!page) return []
  return page.items
    .filter(
      (run) => run.project_id === projectId && (run.status === 'failed' || run.status === 'error'),
    )
    .map((run) => ({
      id: `${run.kind}:${run.id}`,
      rank: 2,
      weight: Date.parse(run.started_at),
      category: '最近执行失败',
      title: `${run.target_name}执行${run.status === 'failed' ? '失败' : '异常'}`,
      description: `${run.kind === 'api' ? '接口' : '流程'} · ${run.started_at}`,
      scope: `最近运行已载入 ${page.items.length}/${page.total} 条 · 不代表全部失败历史`,
      href: recentExecutionPath(run),
      action: run.kind === 'api' ? '查看接口冻结详情' : '查看执行报告',
    }))
}

export function recentExecutionPath(run: RecentExecution): string {
  if (run.kind === 'workflow') return reportExecutionPath(run.project_id, { executionId: run.id })
  return `${projectPath(run.project_id, 'apis')}?${new URLSearchParams({ focus: run.target_id, execution: run.id })}`
}

function coverageGaps(projectId: string, impact?: ImpactRunSummary): PriorityIssue[] {
  if (!impact || impact.summary.gap_count <= 0) return []
  return [
    {
      id: `impact:${impact.id}`,
      rank: 3,
      weight: impact.summary.gap_count,
      category: '覆盖缺口',
      title: `${impact.title}有 ${impact.summary.gap_count} 处测试缺口`,
      description: `覆盖 ${impact.summary.coverage_percent}% · ${impact.change_count} 项变更`,
      scope: `最新影响分析 ${impact.id} · 来源 ${impact.source_ref}`,
      href: projectPath(projectId, 'impact'),
      action: '打开影响分析',
    },
  ]
}

function flakyAssets(projectId: string, page?: Page<FlakyRecord>): PriorityIssue[] {
  if (!page) return []
  return page.items
    .filter((record) => record.project_id === projectId && record.flaky_score > 0)
    .map((record) => ({
      id: `flaky:${record.id}`,
      rank: 4,
      weight: record.flaky_score,
      category: 'Flaky 资产',
      title: `${record.target_type}:${record.target_id}@${record.target_version} 执行不稳定`,
      description: `得分 ${record.flaky_score} · ${record.quarantined ? '已隔离' : '未隔离'} · ${record.total_runs} 次运行中失败 ${record.failed_runs} 次`,
      scope: `Flaky 记录已载入 ${page.items.length}/${page.total} 项 · 最后更新 ${record.updated_at}`,
      href: projectPath(projectId, 'quality'),
      action: '打开质量中心',
    }))
}
