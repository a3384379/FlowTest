import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Card, Input, Select, Space, Typography } from 'antd'
import CatalogPagination from '../../components/CatalogPagination'
import QueryFailureNotice from '../../components/QueryFailureNotice'
import { useCatalogQuery } from '../../lib/catalog-query'
import { useRouteScopedState } from '../../lib/use-route-scoped-state'
import {
  listReportFilterOptions,
  type ReportFilterKind,
  type ReportFilterOption,
} from './report-service'
import type { useReportScope } from './report-scope'

type Props = {
  projectId: string | null
  state: ReturnType<typeof useReportScope>
  onRefresh: () => void
}

export default function ReportFilters({ projectId, state, onRefresh }: Props) {
  return (
    <Card
      style={{ marginBottom: 16 }}
      title="报告范围"
      extra={
        <Space>
          <Button onClick={state.resetFilters}>重置筛选</Button>
          <Button disabled={!state.scope || !projectId} onClick={onRefresh}>
            刷新报告
          </Button>
        </Space>
      }
    >
      <Space wrap align="end">
        <label>
          开始日期（UTC）
          <Input
            aria-label="报告开始日期"
            type="date"
            value={state.filters.from}
            onChange={(event) => state.setFilter('from', event.target.value)}
          />
        </label>
        <label>
          结束日期（UTC，含当日）
          <Input
            aria-label="报告结束日期"
            type="date"
            value={state.filters.to}
            onChange={(event) => state.setFilter('to', event.target.value)}
          />
        </label>
        <Select
          aria-label="执行状态"
          style={{ width: 150 }}
          value={state.filters.status}
          onChange={(value) => state.setFilter('status', value)}
          options={[
            { value: '', label: '全部状态' },
            { value: 'queued', label: '排队中' },
            { value: 'running', label: '运行中' },
            { value: 'passed', label: '仅通过' },
            { value: 'failed', label: '仅失败' },
            { value: 'cancelled', label: '已取消' },
          ]}
        />
        <Select
          aria-label="报告来源"
          style={{ width: 150 }}
          value={state.filters.source}
          onChange={(value) => state.setFilter('source', value)}
          options={[
            { value: '', label: '全部来源' },
            { value: 'workflow', label: '流程运行 / 未记录来源' },
            { value: 'case', label: '用例直接运行' },
            { value: 'plan', label: '计划运行' },
            { value: 'preview', label: '沙箱预览' },
          ]}
        />
        {(['workflow', 'environment', 'case', 'plan'] as const).map((kind) => (
          <ReportResourceFilter
            key={`${projectId}:${kind}`}
            projectId={projectId}
            kind={kind}
            value={state.filters[kind]}
            onChange={(value) => state.setFilter(kind, value)}
          />
        ))}
      </Space>
      <Typography.Paragraph type="secondary" style={{ margin: '12px 0 0' }}>
        列表、总数、趋势和失败分类共用以上范围；按执行开始时间统计，最多 90
        天。对象选项来自本项目全部执行历史（含已归档对象），显示当前名称。记录按开始时间倒序排列。缺少正式来源且无法关联的旧记录归入“流程运行
        / 未记录来源”，不推断到具体计划。
      </Typography.Paragraph>
      {state.error && <Alert type="error" showIcon title={state.error} />}
    </Card>
  )
}

function ReportResourceFilter({
  projectId,
  kind,
  value,
  onChange,
}: {
  projectId: string | null
  kind: ReportFilterKind
  value: string
  onChange: (value: string) => void
}) {
  const labels: Record<ReportFilterKind, string> = {
    workflow: '流程',
    environment: '环境',
    case: '用例',
    plan: '计划',
  }
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useRouteScopedState(projectId, kind, '')
  const [selected, setSelected] = useRouteScopedState<ReportFilterOption | null>(
    projectId,
    kind,
    null,
  )
  const query = useCatalogQuery(
    `report-options:${kind}`,
    projectId,
    (page) => listReportFilterOptions(projectId!, kind, page, search),
    open,
    search,
  )
  const current = useQuery({
    queryKey: ['report-filter-option', projectId, kind, value],
    queryFn: () => listReportFilterOptions(projectId!, kind, 1, '', value),
    enabled: Boolean(projectId && value),
  })
  const items = new Map((query.data?.items ?? []).map((item) => [item.id, item]))
  if (selected) items.set(selected.id, selected)
  current.data?.items.forEach((item) => items.set(item.id, item))
  if (value && !items.has(value))
    items.set(value, { id: value, name: `${labels[kind]} ID：${value}` })
  return (
    <Select
      aria-label={`报告${labels[kind]}筛选`}
      style={{ width: 190 }}
      placeholder={`全部${labels[kind]}`}
      value={value || undefined}
      disabled={!projectId}
      allowClear
      loading={query.isFetching || current.isFetching}
      showSearch={{ filterOption: false, onSearch: setSearch }}
      onOpenChange={setOpen}
      options={[...items.values()].map((item) => ({ value: item.id, label: item.name }))}
      onChange={(id: string | undefined) => {
        setSelected(items.get(id ?? '') ?? null)
        onChange(id ?? '')
      }}
      popupRender={(menu) => (
        <>
          {menu}
          <QueryFailureNotice queries={[current]} />
          <CatalogPagination query={query} label={labels[kind]} />
        </>
      )}
    />
  )
}
