import { useQuery } from '@tanstack/react-query'
import { Pagination, Select, Space } from 'antd'
import { useEffect, useState } from 'react'

import QueryFailureNotice from '../../components/QueryFailureNotice'
import {
  getContractService,
  getPactContract,
  listContractServices,
  listPactContracts,
} from './contract-hub-service'
import { getContractRun, listContractRuns } from './contract-service'

type ReferenceKind = 'service' | 'pact' | 'run'
type ReferenceOption = { value: string; label: string }

export default function ContractReferencePicker({
  projectId,
  kind,
  label,
  value,
  onChange,
  disabled,
  allowClear = true,
  onReadyChange,
}: {
  projectId: string | null
  kind: ReferenceKind
  label: string
  value?: string | null
  onChange?: (id: string | undefined) => void
  disabled?: boolean
  allowClear?: boolean
  onReadyChange?: (ready: boolean) => void
}) {
  const state = useReferenceState(projectId, kind, value)
  const { directory, selected, ready, text, page, options, setOpen, setPage, search, loading } =
    state
  useEffect(() => onReadyChange?.(ready), [onReadyChange, ready])
  return (
    <Space orientation="vertical" size={4} style={{ width: 280, maxWidth: '100%' }}>
      <QueryFailureNotice queries={[selected]} />
      <Select
        aria-label={label}
        style={{ width: '100%', minWidth: 0 }}
        placeholder={`搜索${label}`}
        value={value ?? undefined}
        disabled={disabled || !projectId}
        allowClear={allowClear}
        showSearch
        filterOption={false}
        searchValue={text}
        onSearch={search}
        onOpenChange={setOpen}
        options={options}
        loading={loading}
        notFoundContent={directory.isError ? '目录读取失败' : '没有匹配的契约对象'}
        onChange={onChange}
        popupRender={(menu) => (
          <div onMouseDown={(event) => event.preventDefault()}>
            <QueryFailureNotice queries={[directory]} />
            {!directory.isError && menu}
            <Pagination
              aria-label={`${label}选项分页`}
              size="small"
              current={page}
              pageSize={20}
              total={directory.data?.total ?? 0}
              showSizeChanger={false}
              showTotal={(total) => `共 ${total} 项`}
              onChange={setPage}
            />
          </div>
        )}
      />
    </Space>
  )
}

function useReferenceState(projectId: string | null, kind: ReferenceKind, value?: string | null) {
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  const [page, setPage] = useState(1)
  const term = useSearchTerm(text)
  const directory = useQuery({
    queryKey: ['contract-reference-options', projectId, kind, text.trim(), page],
    queryFn: () => readOptions(projectId!, kind, text.trim(), page),
    enabled: Boolean(projectId && open && term === text.trim()),
  })
  const selected = useQuery({
    queryKey: ['contract-reference', projectId, kind, value],
    queryFn: () => readReference(projectId!, kind, value!),
    enabled: Boolean(projectId && value),
  })
  const ready = referenceReady(value, selected)
  const options = term === text.trim() ? (directory.data?.items ?? []) : []
  function search(next: string) {
    setText(next)
    setPage(1)
  }
  return {
    directory,
    selected,
    ready,
    text,
    page,
    setOpen,
    setPage,
    search,
    options: includeReference(options, value, selected.data),
    loading: referenceLoading(directory.isFetching, selected.isFetching, term !== text.trim()),
  }
}

function includeReference(
  options: ReferenceOption[],
  value: string | null | undefined,
  selection?: ReferenceOption,
) {
  if (!selection || selection.value !== value || options.some((item) => item.value === value))
    return options
  return [selection, ...options]
}

function referenceReady(
  value: string | null | undefined,
  selected: { isSuccess: boolean; data?: ReferenceOption },
) {
  return !value || (selected.isSuccess && selected.data?.value === value)
}

function referenceLoading(directory: boolean, selected: boolean, searching: boolean) {
  return directory || selected || searching
}

async function readOptions(projectId: string, kind: ReferenceKind, search: string, page: number) {
  if (kind === 'service') {
    const result = await listContractServices(projectId, page, 20, search)
    return {
      total: result.total,
      items: result.items.map((item) => ({ value: item.id, label: item.display_name })),
    }
  }
  if (kind === 'pact') {
    const result = await listPactContracts(projectId, page, 20, search)
    return {
      total: result.total,
      items: result.items.map((item) => ({
        value: item.id,
        label: `${item.consumer_name} ${item.consumer_version} → ${item.provider_name}`,
      })),
    }
  }
  const result = await listContractRuns(projectId, page, 20, search)
  return {
    total: result.total,
    items: result.items.map((item) => ({
      value: item.id,
      label: `${item.source_name} · ${item.created_at}`,
    })),
  }
}

async function readReference(
  projectId: string,
  kind: ReferenceKind,
  id: string,
): Promise<ReferenceOption> {
  if (kind === 'service') {
    const item = await getContractService(projectId, id)
    return { value: item.id, label: item.display_name }
  }
  if (kind === 'pact') {
    const { contract: item } = await getPactContract(projectId, id)
    return {
      value: item.id,
      label: `${item.consumer_name} ${item.consumer_version} → ${item.provider_name}`,
    }
  }
  const item = await getContractRun(projectId, id)
  return { value: item.id, label: `${item.source_name} · ${item.created_at}` }
}

function useSearchTerm(text: string): string {
  const [term, setTerm] = useState(text.trim())
  useEffect(() => {
    const timer = window.setTimeout(() => setTerm(text.trim()), 250)
    return () => window.clearTimeout(timer)
  }, [text])
  return term
}
