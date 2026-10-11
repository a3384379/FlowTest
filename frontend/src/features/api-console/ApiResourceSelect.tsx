import { useState } from 'react'
import { Select, Space, Tag } from 'antd'
import CatalogPagination from '../../components/CatalogPagination'
import type { ApiDefinition } from '../../lib/api'
import { useCatalogQuery } from '../../lib/catalog-query'
import { useRouteScopedState } from '../../lib/use-route-scoped-state'
import { listApis } from './api-service'

type Props = {
  id?: string
  projectId?: string | null
  known?: ApiDefinition[]
  value?: string
  onChange?: (id: string) => void
  onSelection?: (api: ApiDefinition) => void
  label: string
  disabled?: boolean
}

export default function ApiResourceSelect(props: Props) {
  if (!props.projectId)
    return (
      <Select
        id={props.id}
        aria-label={props.label}
        value={props.value}
        disabled={props.disabled}
        options={(props.known ?? []).map((api) => ({ value: api.id, label: api.name }))}
        onChange={(id) => {
          const api = props.known?.find((item) => item.id === id)
          if (api) props.onSelection?.(api)
          props.onChange?.(id)
        }}
      />
    )
  return <ProjectApiResourceSelect {...props} />
}

function ProjectApiResourceSelect({
  id,
  projectId,
  known = [],
  value,
  onChange,
  onSelection,
  label,
  disabled = false,
}: Props) {
  const [open, setOpen] = useState(false)
  const scope = id ?? label
  const [search, setSearch] = useRouteScopedState(projectId ?? null, scope, '')
  const [selected, setSelected] = useRouteScopedState<ApiDefinition | undefined>(
    projectId ?? null,
    scope,
    undefined,
  )
  const query = useCatalogQuery(
    `api-options:${scope}`,
    projectId ?? null,
    (page) => listApis(projectId!, { page, pageSize: 20, search }),
    open,
    search,
  )
  const items = apiOptions(known, selected, value, query.data?.items)
  return (
    <Select
      id={id}
      aria-label={label}
      value={value}
      disabled={disabled}
      loading={query.isFetching}
      showSearch={{ filterOption: false, onSearch: setSearch }}
      placeholder="搜索或分页选择接口"
      onOpenChange={setOpen}
      options={[...items.values()].map((item) => ({
        value: item.id,
        label: (
          <Space size={4}>
            <span className="api-resource-option-name">{item.name}</span>
            <Tag>v{item.current_version}</Tag>
          </Space>
        ),
        disabled: !item.is_active,
      }))}
      onChange={(id) => {
        const item = items.get(id)
        if (item) {
          setSelected(item)
          onSelection?.(item)
          onChange?.(id)
        }
      }}
      popupRender={(menu) => (
        <>
          {menu}
          <CatalogPagination query={query} label="接口" />
        </>
      )}
    />
  )
}

function apiOptions(
  known: ApiDefinition[],
  selected: ApiDefinition | undefined,
  value: string | undefined,
  page: ApiDefinition[] | undefined,
) {
  const items = new Map((page ?? known).map((item) => [item.id, item]))
  if (selected) items.set(selected.id, selected)
  const current = known.find((item) => item.id === value)
  if (current && !items.has(current.id)) items.set(current.id, current)
  return items
}
