import { Alert, Button, Pagination, Select, Space, Typography } from 'antd'
import { useEffect, useState } from 'react'

import { apiErrorMessage, type Page, type Workflow } from '../lib/api'
import { useRouteScopedState } from '../lib/use-route-scoped-state'
import { getWorkflow, listWorkflows } from '../features/workflows/workflow-service'

export default function WorkflowResourceSelect({
  projectId,
  value,
  workflows,
  disabled,
  label,
  onChange,
}: {
  projectId?: string | null
  value?: string
  workflows: Workflow[]
  disabled: boolean
  label: string
  onChange: (workflow: Workflow) => void
}) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useRouteScopedState(projectId ?? null, null, '')
  const [page, setPage] = useRouteScopedState(projectId ?? null, search, 1)
  const [result, setResult] = useRouteScopedState<Page<Workflow> | undefined>(
    projectId ?? null,
    `${search}:${page}`,
    undefined,
  )
  const [selected, setSelected] = useRouteScopedState<Workflow | undefined>(
    projectId ?? null,
    value ?? null,
    undefined,
  )
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [retry, setRetry] = useState(0)
  const knownSelection = workflows.some((workflow) => workflow.id === value)
  useEffect(() => {
    if (!projectId || !value || knownSelection) return
    let active = true
    void getWorkflow(projectId, value)
      .then((workflow) => {
        if (active && workflow.project_id === projectId) setSelected(workflow)
      })
      .catch((cause: unknown) => {
        if (active) setError(apiErrorMessage(cause))
      })
    return () => {
      active = false
    }
  }, [projectId, value, knownSelection, retry, setSelected]) // Setters retain the request's resource scope.
  useEffect(() => {
    if (!open || !projectId) return
    let active = true
    const timer = window.setTimeout(() => {
      setLoading(true)
      setError(null)
      void listWorkflows(projectId, { page, pageSize: 20, search })
        .then((next) => {
          if (active) setResult(next)
        })
        .catch((cause: unknown) => {
          if (active) setError(apiErrorMessage(cause))
        })
        .finally(() => {
          if (active) setLoading(false)
        })
    }, 200)
    return () => {
      active = false
      window.clearTimeout(timer)
    }
  }, [open, page, projectId, search, retry, setResult])
  const options = resourceOptions(workflows, result, selected, projectId, search)
  return (
    <Select
      aria-label={label}
      value={value}
      disabled={disabled}
      showSearch={{ filterOption: false, onSearch: setSearch }}
      loading={loading}
      placeholder="搜索或分页选择已发布流程"
      onOpenChange={setOpen}
      options={options.map((workflow) => ({
        value: workflow.id,
        label: `${workflow.name} · v${workflow.current_version}`,
      }))}
      onChange={(id) => {
        const workflow = options.find((item) => item.id === id)
        if (workflow) onChange(workflow)
      }}
      popupRender={(menu) => (
        <>
          {error && (
            <Alert
              type="error"
              title={error}
              action={<Button onClick={() => setRetry((value) => value + 1)}>重试</Button>}
            />
          )}
          {menu}
          {result && (
            <Space orientation="vertical" className="workflow-resource-pagination">
              <Typography.Text type="secondary">
                目录共 {result.total} 项；只可选择已发布流程。本页未发布项已隐藏。
              </Typography.Text>
              <Pagination
                size="small"
                current={page}
                pageSize={20}
                total={result.total}
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

function resourceOptions(
  known: Workflow[],
  page: Page<Workflow> | undefined,
  selected: Workflow | undefined,
  projectId: string | null | undefined,
  search: string,
) {
  const catalog = page ? page.items : known
  const items = search ? catalog : [...known, ...catalog]
  const byId = new Map(items.map((workflow) => [workflow.id, workflow]))
  if (selected) byId.set(selected.id, selected)
  return [...byId.values()].filter(
    (workflow) =>
      (!projectId || workflow.project_id === projectId) && (workflow.current_version ?? 0) > 0,
  )
}
