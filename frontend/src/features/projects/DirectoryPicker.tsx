import { useQuery } from '@tanstack/react-query'
import { Button, Input, Pagination, Select, Space, Spin, Typography } from 'antd'
import { useEffect, useState } from 'react'

import QueryFailureNotice from '../../components/QueryFailureNotice'
import { searchMemberCandidates, searchTeams, searchUsers } from './access-service'

type DirectorySource =
  { kind: 'project-user'; projectId: string } | { kind: 'user' } | { kind: 'team' }
type Option = { value: string; label: string; disabled?: boolean }

export default function DirectoryPicker({
  source,
  label,
  value,
  onChange,
  disabled = false,
  selectedLabel,
}: {
  source: DirectorySource
  label: string
  value?: string | null
  onChange?: (value: string | undefined) => void
  disabled?: boolean
  selectedLabel?: string
}) {
  const [advanced, setAdvanced] = useState(false)
  const state = useDirectory(source)
  const [selected, setSelected] = useState<Option | null>(null)
  const options = includeSelection(state.options, value, selected, selectedLabel)
  return (
    <Space orientation="vertical" size={4}>
      {advanced ? (
        <Input
          aria-label={`${label} ID`}
          placeholder="输入完整 UUID"
          disabled={disabled}
          value={value ?? ''}
          onChange={(event) => onChange?.(event.target.value || undefined)}
        />
      ) : (
        <Select
          aria-label={label}
          className="management-select"
          placeholder={`搜索${label}`}
          value={value}
          disabled={disabled}
          allowClear
          showSearch
          filterOption={false}
          searchValue={state.text}
          onSearch={state.search}
          onOpenChange={state.setOpen}
          loading={state.searching || state.query.isFetching}
          options={options}
          onChange={(id, option) => {
            setSelected((option as Option | undefined) ?? null)
            onChange?.(id)
          }}
          notFoundContent={
            <DirectoryEmpty
              loading={state.searching || state.query.isFetching}
              failed={state.query.isError}
            />
          }
          popupRender={(menu) => (
            <div onMouseDown={(event) => event.preventDefault()}>
              <QueryFailureNotice queries={[state.query]} />
              {state.query.isError ? (
                <Typography.Text type="danger">目录读取失败，请重试或使用已知 ID</Typography.Text>
              ) : (
                menu
              )}
              <Pagination
                size="small"
                current={state.page}
                pageSize={20}
                total={state.query.data?.total ?? 0}
                showSizeChanger={false}
                showTotal={(total) => `共 ${total} 条`}
                onChange={state.setPage}
              />
            </div>
          )}
        />
      )}
      <Button type="link" size="small" disabled={disabled} onClick={() => setAdvanced(!advanced)}>
        {advanced ? '返回名称搜索' : '按 ID 输入'}
      </Button>
    </Space>
  )
}

function useDirectory(source: DirectorySource) {
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  const [page, setPage] = useState(1)
  const term = useDebouncedText(text)
  const query = useQuery({
    queryKey: ['access-directory', source, text.trim(), page],
    queryFn: () => readDirectory(source, text.trim(), page),
    enabled: open && term === text.trim(),
  })
  function search(value: string) {
    setText(value)
    setPage(1)
  }
  return {
    open,
    setOpen,
    text,
    search,
    page,
    setPage,
    query,
    searching: term !== text.trim(),
    options: term === text.trim() ? (query.data?.options ?? []) : [],
  }
}

async function readDirectory(source: DirectorySource, query: string, page: number) {
  const input = { query, page, page_size: 20 }
  if (source.kind === 'team') {
    const result = await searchTeams(input)
    return {
      total: result.total,
      options: result.items.map((team) => ({ value: team.id, label: team.name })),
    }
  }
  const result =
    source.kind === 'user'
      ? await searchUsers(input)
      : await searchMemberCandidates(source.projectId, input)
  return {
    total: result.total,
    options: result.items.map((user) => ({
      value: user.id,
      label: `${user.display_name} (${user.email})${user.is_active ? '' : '（已停用）'}`,
      disabled: !user.is_active,
    })),
  }
}

function includeSelection(
  options: Option[],
  value: string | null | undefined,
  selected: Option | null,
  label?: string,
): Option[] {
  if (!value || options.some((option) => option.value === value)) return options
  const retained = selected?.value === value ? selected : { value, label: label ?? value }
  return [retained, ...options]
}

function DirectoryEmpty({ loading, failed }: { loading: boolean; failed: boolean }) {
  if (loading) return <Spin size="small" />
  return failed ? '目录读取失败' : '没有匹配的可授权对象'
}

function useDebouncedText(text: string): string {
  const [term, setTerm] = useState(text.trim())
  useEffect(() => {
    const timer = window.setTimeout(() => setTerm(text.trim()), 250)
    return () => window.clearTimeout(timer)
  }, [text])
  return term
}
