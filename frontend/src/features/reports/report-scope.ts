import { useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useRouteScopedState } from '../../lib/use-route-scoped-state'

export type ReportScope = {
  started_from: string
  started_until: string
  status?: 'queued' | 'running' | 'passed' | 'failed' | 'cancelled'
  workflow_id?: string
  environment_id?: string
  source_case_id?: string
  source_plan_id?: string
  source?: 'workflow' | 'case' | 'plan' | 'preview'
}

export type ReportFilterKey =
  'from' | 'to' | 'status' | 'workflow' | 'environment' | 'case' | 'plan' | 'source'

const parameterNames: Record<ReportFilterKey, string> = {
  from: 'reportFrom',
  to: 'reportTo',
  status: 'reportStatus',
  workflow: 'reportWorkflow',
  environment: 'reportEnvironment',
  case: 'reportCase',
  plan: 'reportPlan',
  source: 'reportSource',
}

export function defaultReportPeriod(now = new Date()) {
  const end = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()))
  const start = new Date(end.getTime() - 6 * 86400000)
  return { from: start.toISOString().slice(0, 10), to: end.toISOString().slice(0, 10) }
}

export function parseReportScope(params: URLSearchParams, fallback = defaultReportPeriod()) {
  const filters = Object.fromEntries(
    Object.entries(parameterNames).map(([key, name]) => [key, params.get(name) ?? '']),
  ) as Record<ReportFilterKey, string>
  if (!filters.from && !filters.to) Object.assign(filters, fallback)
  const error = scopeError(filters)
  const pageValue = Number(params.get('reportPage') ?? 1)
  const page = Number.isSafeInteger(pageValue) && pageValue > 0 ? pageValue : 1
  const scope = error ? null : scopeForFilters(filters)
  return { filters, scope, error, page }
}

function scopeForFilters(filters: Record<ReportFilterKey, string>): ReportScope {
  return {
    started_from: `${filters.from}T00:00:00.000Z`,
    started_until: new Date(Date.parse(filters.to) + 86400000).toISOString(),
    status: (filters.status || undefined) as ReportScope['status'],
    source: (filters.source || undefined) as ReportScope['source'],
    workflow_id: filters.workflow || undefined,
    environment_id: filters.environment || undefined,
    source_case_id: filters.case || undefined,
    source_plan_id: filters.plan || undefined,
  }
}

function scopeError(filters: Record<ReportFilterKey, string>): string | null {
  const validDate = (value: string) =>
    /^\d{4}-\d{2}-\d{2}$/.test(value) &&
    Number.isFinite(Date.parse(value)) &&
    new Date(value).toISOString().slice(0, 10) === value
  if (!validDate(filters.from) || !validDate(filters.to)) return '请选择完整且有效的起止日期'
  const days = (Date.parse(filters.to) - Date.parse(filters.from)) / 86400000 + 1
  if (days < 1 || days > 90) return '日期范围须为 1 至 90 天（含首尾日期）'
  if (
    filters.status &&
    !['queued', 'running', 'passed', 'failed', 'cancelled'].includes(filters.status)
  )
    return 'URL 中的执行状态无效'
  if (filters.source && !['workflow', 'case', 'plan', 'preview'].includes(filters.source))
    return 'URL 中的报告来源无效'
  if (
    [filters.workflow, filters.environment, filters.case, filters.plan].some(
      (value) => value && !/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value),
    )
  )
    return 'URL 中的筛选对象 ID 无效'
  return null
}

export function useReportScope(projectId: string | null, listMode: boolean) {
  const [params, setParams] = useSearchParams()
  const [fallback] = useRouteScopedState(projectId, 'report-period', defaultReportPeriod())
  const result = parseReportScope(params, fallback)
  useEffect(() => {
    if (!listMode || !projectId || params.has('reportFrom') || params.has('reportTo')) return
    const next = new URLSearchParams(params)
    next.set('reportFrom', fallback.from)
    next.set('reportTo', fallback.to)
    setParams(next, { replace: true })
  }, [fallback, listMode, params, projectId, setParams])
  return {
    ...result,
    setFilter: (key: ReportFilterKey, value: string) => {
      const next = new URLSearchParams(params)
      if (value) next.set(parameterNames[key], value)
      else next.delete(parameterNames[key])
      next.delete('reportPage')
      setParams(next)
    },
    setPage: (page: number) => {
      const next = new URLSearchParams(params)
      next.set('reportPage', String(page))
      setParams(next)
    },
    resetFilters: () => {
      const next = new URLSearchParams(params)
      Object.values(parameterNames).forEach((name) => next.delete(name))
      next.delete('reportPage')
      const period = defaultReportPeriod()
      next.set('reportFrom', period.from)
      next.set('reportTo', period.to)
      setParams(next)
    },
  }
}
