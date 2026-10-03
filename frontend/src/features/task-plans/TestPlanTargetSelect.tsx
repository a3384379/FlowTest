import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Pagination, Select, Space, Typography } from 'antd'
import { useEffect, useState } from 'react'

import { apiErrorMessage } from '../../lib/api'
import { useRouteScopedState } from '../../lib/use-route-scoped-state'
import { useProjectContext } from '../projects/use-project-context'
import {
  getPlanTargetAsset,
  listPlanTargetAssets,
  type TestPlanTargetAsset,
  type TestPlanTargetType,
} from './task-plan-service'

export default function TestPlanTargetSelect({
  type,
  label,
  known,
  value,
  onChange,
  onSelection,
}: {
  type: TestPlanTargetType
  label: string
  known: TestPlanTargetAsset[]
  value?: string
  onChange?: (value: string) => void
  onSelection: (asset: TestPlanTargetAsset) => void
}) {
  const { projectId } = useProjectContext()
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [query, setQuery] = useState('')
  const [page, setPage] = useRouteScopedState(projectId, `${type}:${query}`, 1)
  useEffect(() => {
    const timer = window.setTimeout(() => setQuery(search), 200)
    return () => window.clearTimeout(timer)
  }, [search])
  const catalog = useQuery({
    queryKey: ['test-plan-targets', projectId, type, query, page],
    queryFn: () => listPlanTargetAssets(projectId!, type, page, query),
    enabled: Boolean(projectId && open),
  })
  const selection = useQuery({
    queryKey: ['test-plan-target', projectId, type, value],
    queryFn: () => getPlanTargetAsset(projectId!, type, value!),
    enabled: Boolean(projectId && value && !known.some((item) => item.id === value)),
  })
  const assets = selectableAssets(projectId, known, catalog.data?.items, selection.data, value)
  return (
    <Select
      aria-label={label}
      value={value}
      placeholder="搜索或分页选择已发布资源"
      showSearch={{ filterOption: false, onSearch: (value) => setSearch(value.slice(0, 200)) }}
      onOpenChange={setOpen}
      loading={catalog.isFetching}
      options={assets.map((asset) => ({
        value: asset.id,
        label: `${asset.name} · v${asset.current_version}`,
      }))}
      onChange={(id) => {
        const asset = assets.find((item) => item.id === id)
        if (asset) {
          onChange?.(id)
          onSelection(asset)
        }
      }}
      popupRender={(menu) => (
        <>
          {catalog.isError && (
            <Alert
              type="error"
              title={apiErrorMessage(catalog.error)}
              action={<Button onClick={() => void catalog.refetch()}>重试</Button>}
            />
          )}
          {menu}
          {catalog.data && (
            <Space orientation="vertical" className="workflow-resource-pagination">
              <Typography.Text type="secondary">
                目录共 {catalog.data.total} 项；本页只显示已发布资源。
              </Typography.Text>
              <Pagination
                size="small"
                current={page}
                pageSize={20}
                total={catalog.data.total}
                showSizeChanger={false}
                onChange={setPage}
              />
            </Space>
          )}
        </>
      )}
    />
  )
}

function selectableAssets(
  projectId: string | null,
  known: TestPlanTargetAsset[],
  catalog: TestPlanTargetAsset[] | undefined,
  selected: TestPlanTargetAsset | undefined,
  value: string | undefined,
) {
  const items = catalog ?? known
  const byId = new Map(items.map((item) => [item.id, item]))
  const currentSelection = selected ?? known.find((item) => item.id === value)
  if (currentSelection) byId.set(currentSelection.id, currentSelection)
  return [...byId.values()].filter(
    (asset) =>
      asset.project_id === projectId && asset.current_version !== null && asset.current_version > 0,
  )
}
