import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Card, Select, Space, Typography } from 'antd'
import CatalogPagination from '../../components/CatalogPagination'
import QueryFailureNotice from '../../components/QueryFailureNotice'
import { useCatalogQuery } from '../../lib/catalog-query'
import { useRouteScopedState } from '../../lib/use-route-scoped-state'
import { listAssetEnvironmentOptions } from './asset-workspace-service'
import type { useAssetCatalogScope } from './asset-catalog-scope'

export default function AssetCatalogFilters({
  projectId,
  state,
  onRefresh,
}: {
  projectId: string | null
  state: ReturnType<typeof useAssetCatalogScope>
  onRefresh: () => void
}) {
  return (
    <Card
      style={{ marginBottom: 16 }}
      title="任务筛选"
      extra={
        <Space>
          <Button onClick={state.reset}>重置筛选</Button>
          <Button disabled={!projectId || !state.scope} onClick={onRefresh}>
            刷新目录
          </Button>
        </Space>
      }
    >
      <Space wrap>
        <Select
          aria-label="资产发布状态"
          value={state.filters.publication}
          style={{ width: 170 }}
          onChange={(value) => state.setFilter('publication', value)}
          options={[
            { value: '', label: '全部发布状态' },
            { value: 'published', label: '已有发布版本' },
            { value: 'unpublished', label: '仅草稿（从未发布）' },
          ]}
        />
        <Select
          aria-label="资产最近结果"
          value={state.filters.result}
          style={{ width: 150 }}
          onChange={(value) => state.setFilter('result', value)}
          options={[
            { value: '', label: '全部最近结果' },
            { value: 'unrun', label: '未运行' },
            { value: 'queued', label: '排队中' },
            { value: 'running', label: '运行中' },
            { value: 'passed', label: '通过' },
            { value: 'failed', label: '失败' },
            { value: 'cancelled', label: '已取消' },
            { value: 'quarantined', label: '已隔离' },
          ]}
        />
        <CatalogEnvironmentFilter
          key={projectId}
          projectId={projectId}
          value={state.filters.environment}
          resolveValue={Boolean(state.scope)}
          onChange={(value) => state.setFilter('environment', value)}
        />
        <Select
          aria-label="资产排序"
          value={state.filters.order}
          style={{ width: 160 }}
          onChange={(value) => state.setFilter('order', value)}
          options={[
            { value: 'updated_desc', label: '最近修改优先' },
            { value: 'name_asc', label: '名称升序' },
            { value: 'name_desc', label: '名称降序' },
            { value: 'latest_run_desc', label: '最近运行优先' },
          ]}
        />
      </Space>
      <Typography.Paragraph type="secondary" style={{ margin: '12px 0 0' }}>
        发布状态表示是否存在发布版本。最近结果按所有版本的最近一次运行统计；待开始的计划条目保留排队状态。环境匹配该次运行，套件匹配任一成员的运行环境；无运行记录的资产在全部环境中显示。环境选项含历史已归档环境。目录数量与列表共用筛选。
      </Typography.Paragraph>
      {state.error && <Alert type="error" showIcon title={state.error} />}
    </Card>
  )
}

function CatalogEnvironmentFilter({
  projectId,
  value,
  resolveValue,
  onChange,
}: {
  projectId: string | null
  value: string
  resolveValue: boolean
  onChange: (value: string) => void
}) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useRouteScopedState(projectId, 'asset-environment-filter', '')
  const [selected, setSelected] = useRouteScopedState<{ id: string; name: string } | null>(
    projectId,
    'asset-environment-filter',
    null,
  )
  const query = useCatalogQuery(
    'asset-environment-options',
    projectId,
    (page) => listAssetEnvironmentOptions(projectId!, page, search),
    open,
    search,
  )
  const current = useQuery({
    queryKey: ['asset-environment-selected', projectId, value],
    queryFn: () => listAssetEnvironmentOptions(projectId!, 1, '', value),
    enabled: Boolean(projectId && value && resolveValue),
  })
  const items = environmentOptions(query.data?.items, selected, current.data?.items, value)

  return (
    <Select
      aria-label="最近运行环境"
      disabled={!projectId}
      placeholder="全部运行环境"
      value={value || undefined}
      style={{ width: 220 }}
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
          <CatalogPagination query={query} label="运行环境" />
        </>
      )}
    />
  )
}

type EnvironmentOption = { id: string; name: string }
function environmentOptions(
  page: EnvironmentOption[] | undefined,
  selected: EnvironmentOption | null,
  current: EnvironmentOption[] | undefined,
  value: string,
) {
  const items = new Map((page ?? []).map((item) => [item.id, item]))
  if (selected) items.set(selected.id, selected)
  current?.forEach((item) => items.set(item.id, item))
  if (value && !items.has(value)) items.set(value, { id: value, name: `环境 ID：${value}` })
  return items
}
