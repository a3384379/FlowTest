import { apiClient, type Page } from '../../lib/api'

export type SearchResourceType =
  | 'project'
  | 'api'
  | 'workflow'
  | 'test_case'
  | 'test_suite'
  | 'test_plan'
  | 'environment'
  | 'mock_service'
  | 'performance_scenario'
  | 'contract_service'
  | 'impact_run'
  | 'quality_gate'
  | 'release_risk'
  | 'release_policy'

export type SearchResult = {
  resource_type: SearchResourceType
  resource_id: string
  project_id: string
  project_name: string
  title: string
  description: string
  section: string
  path: string
  updated_at: string
}

export async function globalSearch(query: string): Promise<Page<SearchResult>> {
  return (
    await apiClient.get<Page<SearchResult>>('/search', {
      params: { q: query, page: 1, page_size: 20 },
    })
  ).data
}
