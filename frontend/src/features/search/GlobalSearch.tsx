import { SearchOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { Select, Space, Spin, Typography } from 'antd'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { globalSearch, type SearchResourceType, type SearchResult } from './search-service'

const resourceLabels: Record<SearchResourceType, string> = {
  project: '项目',
  api: '接口',
  workflow: '工作流',
  test_case: '测试用例',
  test_suite: '测试套件',
  test_plan: '测试计划',
  environment: '环境',
  mock_service: 'Mock 服务',
  performance_scenario: '性能场景',
  contract_service: '服务',
  impact_run: '影响分析',
  quality_gate: '质量门禁',
  release_risk: '发布风险',
  release_policy: '发布策略',
}

export default function GlobalSearch() {
  const navigate = useNavigate()
  const [searchText, setSearchText] = useState('')
  const query = useDebouncedSearch(searchText)
  const results = useQuery({
    queryKey: ['global-search', query],
    queryFn: () => globalSearch(query),
    enabled: query.length >= 2,
    staleTime: 30_000,
  })
  const options = (results.data?.items ?? []).map((result) => ({
    value: result.path,
    label: <SearchOption result={result} />,
  }))
  return (
    <Select
      aria-label="全局搜索"
      className="global-search"
      showSearch
      allowClear
      filterOption={false}
      searchValue={searchText}
      value={undefined}
      placeholder="搜索项目与资产"
      suffixIcon={<SearchOutlined />}
      popupMatchSelectWidth={520}
      options={options}
      notFoundContent={<SearchEmpty query={query} loading={results.isFetching} />}
      onSearch={setSearchText}
      onClear={() => setSearchText('')}
      onSelect={(path) => {
        if (!path) return
        setSearchText('')
        void navigate(path)
      }}
    />
  )
}

function SearchOption({ result }: { result: SearchResult }) {
  return (
    <Space orientation="vertical" size={0}>
      <Typography.Text strong>{result.title}</Typography.Text>
      <Typography.Text type="secondary">
        {resourceLabels[result.resource_type]} · {result.project_name}
      </Typography.Text>
    </Space>
  )
}

function SearchEmpty({ query, loading }: { query: string; loading: boolean }) {
  if (loading) return <Spin size="small" />
  return query.length < 2 ? '至少输入 2 个字符' : '未找到可访问的资产'
}

function useDebouncedSearch(value: string): string {
  const [debounced, setDebounced] = useState('')
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value.trim()), 250)
    return () => window.clearTimeout(timer)
  }, [value])
  return debounced
}
