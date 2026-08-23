import { apiClient, type ApiDefinition, type Environment, type Page } from '../../lib/api'

export type EvidenceRef = {
  id: string
  source_type: string
  source_ref: string
  revision: string
}

export type ScenarioCandidate = {
  id: string
  kind: string
  title: string
  request_body: Record<string, unknown>
  mutations: Array<{ path: string; operation: string; value: unknown }>
  expected_category: string
  negative: boolean
  evidence_refs: string[]
  confidence: number
  deterministic: boolean
  requires_review: boolean
  tags: string[]
}

export type OracleSpec = {
  id: string
  kind: string
  expression: string
  operator: string
  expected: unknown
  confidence: number
  evidence_refs: string[]
  source_type: string | null
  deterministic: boolean
  requires_review: boolean
  applies_to: string[]
}

export type CoverageEntry = {
  target_ref: string
  dimension: string
  requirement: string
  covered: boolean
  evidence_refs: string[]
  reason: string
  recommended_scenario_kind: string | null
  priority: string
}

export type TestDesignDocument = {
  schema_version: '1.0'
  intent: {
    key: string
    objective: string
    acceptance_criteria: string[]
    evidence_refs: string[]
    confidence: number
    deterministic: boolean
  }
  scenarios: ScenarioCandidate[]
  oracles: OracleSpec[]
  coverage: { entries: CoverageEntry[] }
  evidence_refs: EvidenceRef[]
  warnings: string[]
  confidence: number
  review_requirements: string[]
}

export type TestEngineeringGeneration = {
  fingerprint: string
  design: TestDesignDocument
  persisted: false
}

export type TestEngineeringProposal = {
  change_set_id: string
  status: string
  review_status: 'pending' | 'accepted' | 'rejected'
  fingerprint: string
  design: TestDesignDocument
  scenario_ids: string[]
  applied: boolean
}

export type TestEngineeringApplyResult = {
  change_set_id: string
  test_design_id: string
  workflow_ids: string[]
  test_case_ids: string[]
}

export async function listTestEngineeringApis(projectId: string): Promise<Page<ApiDefinition>> {
  return (
    await apiClient.get<Page<ApiDefinition>>(`/projects/${projectId}/apis`, {
      params: { page: 1, page_size: 100 },
    })
  ).data
}

export async function listTestEngineeringEnvironments(projectId: string): Promise<Environment[]> {
  return (await apiClient.get<Environment[]>(`/projects/${projectId}/environments`)).data
}

export async function generateTestDesign(
  projectId: string,
  apiDefinitionId: string,
): Promise<TestEngineeringGeneration> {
  return (
    await apiClient.post<TestEngineeringGeneration>(
      `/projects/${projectId}/test-engineering/generate`,
      { api_definition_id: apiDefinitionId },
    )
  ).data
}

export async function proposeTestDesign(
  projectId: string,
  input: {
    title: string
    api_definition_id: string
    environment_id: string
    endpoint_variant?: string
    scenario_ids: string[]
  },
): Promise<TestEngineeringProposal> {
  return (
    await apiClient.post<TestEngineeringProposal>(
      `/projects/${projectId}/test-engineering/proposals`,
      input,
    )
  ).data
}

export async function reviewTestDesignProposal(
  projectId: string,
  changeSetId: string,
  accept: boolean,
): Promise<TestEngineeringProposal> {
  return (
    await apiClient.post<TestEngineeringProposal>(
      `/projects/${projectId}/test-engineering/proposals/${changeSetId}/review`,
      { accept, note: '前端人工审核' },
    )
  ).data
}

export async function applyTestDesignProposal(
  projectId: string,
  changeSetId: string,
): Promise<TestEngineeringApplyResult> {
  return (
    await apiClient.post<TestEngineeringApplyResult>(
      `/projects/${projectId}/test-engineering/proposals/${changeSetId}/apply`,
    )
  ).data
}
