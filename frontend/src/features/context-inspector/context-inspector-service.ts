import { apiClient, type Page } from '../../lib/api'

export type ContextStatus =
  'collecting' | 'ready' | 'incomplete' | 'conflicted' | 'expired' | 'closed'

export type EvidenceProviderType =
  | 'repository'
  | 'contract'
  | 'data_profile'
  | 'service_topology'
  | 'existing_test'
  | 'workflow'
  | 'runtime'
  | 'change'
  | 'user_confirmed_rule'
  | 'database'

export type ContextCompleteness = {
  required: EvidenceProviderType[]
  present: EvidenceProviderType[]
  missing: EvidenceProviderType[]
  complete: boolean
}

export type ContextSummary = {
  id: string
  project_id: string
  name: string
  objective: string
  status: ContextStatus
  current_revision: number
  revision_id: string
  revision_fingerprint: string
  completeness: ContextCompleteness
  conflict_count: number
  evidence_count: number
  provider_count: number
  proposal_count: number
  expires_at: string
  created_at: string
  updated_at: string
}

export type KnowledgeFact = { name: string; value: string }
export type KnowledgeNode = { id: string; kind: string; label: string; facts: KnowledgeFact[] }
export type KnowledgeEdge = { source: string; target: string; relation: string }

export type ContextConflict = {
  subject_ref: string
  finding_fingerprints: string[]
  summary: string
}

export type ContextRevision = {
  schema_version: 'flowtest-context-revision-v1'
  repository_revisions: Array<{ source_ref: string; revision: string }>
  contract_revisions: Array<{ source_ref: string; revision: string }>
  data_profile_revisions: Array<{ source_ref: string; revision: string }>
  existing_test_revision: { source_ref: string; revision: string } | null
  knowledge_snapshot: {
    schema_version: 'flowtest-context-knowledge-v1'
    nodes: KnowledgeNode[]
    edges: KnowledgeEdge[]
  }
  conflict_snapshot: {
    schema_version: 'flowtest-context-conflicts-v1'
    conflicts: ContextConflict[]
  }
  completeness: ContextCompleteness
  evidence_fingerprints: string[]
}

export type ProviderSummary = {
  source_type: EvidenceProviderType
  provider_name: string
  provider_version: string
  finding_count: number
  deterministic_count: number
  conflict_count: number
}

export type EvidenceFinding = {
  id: string
  kind: string
  semantic_role: string
  source_ref: string
  source_revision: string
  subject_ref: string
  source_path: string
  source_content: string
  content_role: 'untrusted_data'
  statement: string
  confidence: number
  deterministic: boolean
  semantic_fingerprint: string
}

export type ContextEvidenceItem = {
  id: string
  source_type: EvidenceProviderType
  provider_name: string
  provider_version: string
  source_ref: string
  source_revision: string
  subject_ref: string
  finding: EvidenceFinding
  semantic_role: string
  deterministic: boolean
  confidence: number
  fingerprint: string
  warnings: Array<{ code: string; message: string }>
  redaction_count: number
  created_at: string
  expires_at: string
}

export type ContextProposal = {
  id: string
  title: string
  status: string
  review_status: 'pending' | 'accepted' | 'rejected'
  applied: boolean
  target_workflow_id: string | null
  target_revision: number | null
  source_ref: string | null
  created_at: string
  updated_at: string
}

export type ContextDetail = ContextSummary & {
  organization_id: string
  target_environment_id: string | null
  created_by_type: 'user' | 'service_account'
  created_by_id: string
  closed_at: string | null
  revision: ContextRevision
  providers: ProviderSummary[]
  evidence_items: ContextEvidenceItem[]
  proposals: ContextProposal[]
}

export async function listContexts(projectId: string): Promise<Page<ContextSummary>> {
  return (
    await apiClient.get<Page<ContextSummary>>(`/projects/${projectId}/contexts`, {
      params: { page: 1, page_size: 100 },
    })
  ).data
}

export async function getContext(projectId: string, contextId: string): Promise<ContextDetail> {
  return (await apiClient.get<ContextDetail>(`/projects/${projectId}/contexts/${contextId}`)).data
}
