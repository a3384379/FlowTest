import { useQuery } from '@tanstack/react-query'
import { Button, Input, Select, Space, Typography } from 'antd'
import { useState } from 'react'
import CatalogPagination from '../../components/CatalogPagination'
import QueryFailureNotice from '../../components/QueryFailureNotice'
import { getDeploymentCheck } from '../contracts/contract-hub-service'
import { getImpactRun } from '../impact/impact-service'
import { getPerformanceRun } from '../performance/performance-service'
import { getReleaseRisk } from '../quality/quality-service'
import { getTestPlanRun } from '../task-plans/task-plan-service'
import { getReleaseRunnerEvidence } from './release-gate-service'
import type { ReleaseEvidenceKind } from './release-evidence-types'

export type EvidenceOption = { id: string; label: string; observedAt?: string | null }
export type EvidenceDirectory = {
  isError: boolean
  error: unknown
  isPending: boolean
  isFetching: boolean
  data?: { total: number; page_size: number }
  refetch: () => Promise<unknown>
  page: number
  setPage: (page: number) => void
}

export default function ReleaseEvidencePicker({
  projectId,
  kind,
  label,
  query,
  options,
  availability,
  value,
  onChange,
  onSearch,
  searchValue = '',
}: {
  projectId: string
  kind: ReleaseEvidenceKind
  label: string
  query: EvidenceDirectory
  options: EvidenceOption[]
  availability: string | null
  value?: string
  onChange?: (value: string | undefined) => void
  onSearch?: (term: string) => void
  searchValue?: string
}) {
  const [selected, setSelected] = useState<EvidenceOption | null>(null)
  const [lookupId, setLookupId] = useState('')
  const [searchDraft, setSearchDraft] = useState(searchValue)
  const lookup = useQuery({
    queryKey: ['release-evidence-reference', projectId, kind, lookupId],
    queryFn: () => readEvidenceReference(projectId, kind, lookupId),
    enabled: Boolean(lookupId && !availability),
  })
  function select(id: string | undefined) {
    setSelected(options.find((option) => option.id === id) ?? lookup.data ?? null)
    onChange?.(id)
  }
  const choices = selectedOptions(options, selected, value)
  return (
    <Space orientation="vertical" className="full-width">
      <Typography.Text type="secondary">
        {availability ?? directoryStatus(query, label)}
      </Typography.Text>
      <Select
        aria-label={label}
        value={value}
        disabled={Boolean(availability)}
        allowClear
        showSearch
        optionFilterProp="label"
        placeholder="未选择"
        loading={query.isFetching}
        style={{ width: '100%' }}
        onChange={select}
        options={choices.map((option) => ({
          value: option.id,
          label: option.label,
          observedAt: option.observedAt,
        }))}
        optionRender={(option) => (
          <Space orientation="vertical" size={0}>
            <span>{option.label}</span>
            <Typography.Text type="secondary">{option.value}</Typography.Text>
            <Typography.Text type="secondary">
              生成或完成时间：{option.data.observedAt ?? '未提供'}
            </Typography.Text>
          </Space>
        )}
      />
      {!availability && <CatalogPagination query={query} label={`${label}证据`} />}
      {onSearch && (
        <Input.Search
          aria-label={`${label}跨页搜索`}
          placeholder="按运行/任务ID、关联ID或状态跨页搜索"
          allowClear
          disabled={Boolean(availability)}
          value={searchDraft}
          onChange={(event) => setSearchDraft(event.target.value)}
          onSearch={(term) => {
            setSearchDraft(term.trim())
            onSearch(term.trim())
          }}
          maxLength={200}
        />
      )}
      <Input.Search
        aria-label={`${label}精确ID`}
        placeholder="粘贴完整证据ID，先核对再选入"
        enterButton="核对"
        disabled={Boolean(availability)}
        maxLength={36}
        onSearch={(id) => setLookupId(id.trim())}
      />
      {!availability && <QueryFailureNotice queries={[lookup]} />}
      {lookup.isSuccess && !availability && (
        <Space wrap>
          <Typography.Text>
            {lookup.data.label} · {lookup.data.id}
          </Typography.Text>
          <Button
            onClick={() => {
              setSelected(lookup.data)
              onChange?.(lookup.data.id)
            }}
          >
            使用已核对证据
          </Button>
        </Space>
      )}
    </Space>
  )
}

function selectedOptions(
  options: EvidenceOption[],
  selected: EvidenceOption | null,
  value?: string,
) {
  if (!selected || selected.id !== value || options.some((option) => option.id === value))
    return options
  return [selected, ...options]
}

function directoryStatus(query: EvidenceDirectory, label: string): string {
  if (query.isError) return `${label}目录读取失败，不能按无数据处理`
  if (query.isPending) return `正在读取${label}目录`
  if (query.data?.total === 0) return `当前项目没有${label}证据`
  return '按实际状态和时间核对适用性；过期、失败和不满足策略的证据仍由后端阻断'
}

async function readEvidenceReference(
  projectId: string,
  kind: ReleaseEvidenceKind,
  id: string,
): Promise<EvidenceOption> {
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id))
    throw new Error('请输入完整有效的证据 UUID')
  if (kind === 'quality_gate') {
    const detail = await getTestPlanRun(projectId, id)
    return {
      id: detail.run.id,
      label: `${detail.run.status} · ${detail.run.created_at}`,
      observedAt: detail.run.created_at,
    }
  }
  if (kind === 'contract_compatibility') {
    const record = await getDeploymentCheck(projectId, id)
    return {
      id,
      label: `${record.provider_version} · ${record.decision}`,
      observedAt: record.created_at,
    }
  }
  if (kind === 'impact') {
    const record = await getImpactRun(projectId, id)
    return { id, label: `${record.title} · ${record.status}`, observedAt: record.created_at }
  }
  if (kind === 'release_risk') {
    const record = await getReleaseRisk(projectId, id)
    return { id, label: `${record.title} · ${record.score}`, observedAt: record.created_at }
  }
  if (kind === 'performance') {
    const record = await getPerformanceRun(projectId, id)
    return {
      id,
      label: `v${record.scenario_version} · ${record.status}`,
      observedAt: record.completed_at ?? record.created_at,
    }
  }
  const record = await getReleaseRunnerEvidence(projectId, id)
  return {
    id,
    label: `${record.status} · fence ${record.fencing_token}`,
    observedAt: record.completed_at ?? record.created_at,
  }
}
