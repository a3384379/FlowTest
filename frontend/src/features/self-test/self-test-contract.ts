import * as d from './self-test-decode'

const digest: d.Decoder<string> = (value) => {
  const result = d.text(value)
  if (!/^[0-9a-f]{64}$/.test(result)) throw new d.SelfTestContractError()
  return result
}
const reason: d.Decoder<string> = (value) => {
  const result = d.identifier(value)
  if (!/^[A-Z][A-Z0-9_]{0,99}$/.test(result)) throw new d.SelfTestContractError()
  return result
}
const reasons = d.array(reason, 30)
const readiness = d.choice([
  'ready',
  'needs_input',
  'needs_review',
  'unsupported',
  'blocked',
] as const)
const generationMode = d.choice(['deterministic_mcp', 'host_llm_mcp'] as const)
const generationStage = d.choice([
  'discovering',
  'reading_contract',
  'designing',
  'compiling',
  'proposing',
  'awaiting_review',
  'publishing',
  'ready',
  'blocked',
  'cancelled',
] as const)
const verification = d.choice([
  'pending',
  'matched',
  'mismatched',
  'incomplete',
  'error',
  'unsupported',
] as const)
const installationStatus = d.choice([
  'needs_input',
  'queued',
  'installing',
  'ready',
  'blocked',
  'archived',
] as const)
const scenarioId: d.Decoder<string> = (value) => {
  const result = d.identifier(value)
  if (!/^[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$/.test(result)) throw new d.SelfTestContractError()
  return result
}
const scenarioKey = { scenario_id: scenarioId, variant_key: d.identifier }
const expectedResult = d.object({
  status: d.choice(['passed', 'failed', 'cancelled'] as const),
  error_code: d.nullable(reason),
  phase: d.nullable(d.choice(['main', 'cleanup'] as const)),
})
export const parseActions = d.object({
  can_initialize: d.bool,
  can_generate: d.bool,
  can_execute: d.bool,
  can_cancel: d.bool,
  reason_codes: reasons,
})
export const parseBuilds = d.object({
  runner: d.identifier,
  target: d.identifier,
  fixture: d.identifier,
  verifier: d.identifier,
})
export const parseTemplate = d.object({
  id: d.identifier,
  version: d.identifier,
  title: d.identifier,
  batch_kind: d.choice(['fixed_baseline', 'mcp_generated'] as const),
  pack_digest: digest,
  task_set_digest: digest,
  scenarios: d.nonEmptyArray(
    d.object({
      ...scenarioKey,
      title: d.identifier,
      category: d.choice(['api', 'engine', 'mcp'] as const),
      required: d.bool,
      expected: expectedResult,
    }),
    100,
  ),
  supported_modes: d.array(generationMode, 2),
})
export const parseBinding = d.object({
  id: d.uuid,
  name: d.identifier,
  fingerprint: digest,
  environment_fingerprint: digest,
  runner_instance_id: d.identifier,
  target_instance_id: d.identifier,
  target_display: d.identifier,
  fixture_display: d.identifier,
  builds: parseBuilds,
  runtime_profile: d.choice(['full', 'compose', 'standalone', 'compact'] as const),
  host_status: d.choice(['available', 'not_registered', 'expired'] as const),
  observer_status: d.choice(['available', 'not_configured', 'expired'] as const),
  readiness,
  reason_codes: reasons,
  installations: d.array(
    d.object({ id: d.uuid, pack_digest: digest, status: installationStatus }),
    20,
  ),
  actions: parseActions,
})
export const parsePreview = d.object({
  fingerprint: digest,
  expires_at: d.timestamp,
  binding_id: d.uuid,
  template: parseTemplate,
  can_apply: d.bool,
  checks: d.nonEmptyArray(
    d.object({
      code: reason,
      status: d.choice(['passed', 'blocked', 'warning'] as const),
      message: d.text,
    }),
    30,
  ),
  resources: d.array(
    d.object({
      kind: d.choice([
        'environment',
        'service',
        'api',
        'workflow',
        'case',
        'suite',
        'plan',
      ] as const),
      action: d.choice(['create', 'reuse', 'conflict'] as const),
      count: d.integer,
    }),
    20,
  ),
  conflicts: reasons,
  existing_installation_id: d.nullable(d.uuid),
})
const publishedAsset = d.object({ id: d.uuid, version: d.positive, fingerprint: digest })
const scenarioAssets = { ...scenarioKey, workflow: publishedAsset, case: publishedAsset }
export const parseInstallation = d.object({
  id: d.uuid,
  project_id: d.uuid,
  binding_id: d.uuid,
  template_id: d.identifier,
  template_version: d.identifier,
  pack_digest: digest,
  status: installationStatus,
  revision: d.integer,
  readiness,
  reason_codes: reasons,
  environment_fingerprint: digest,
  mapping: d.nullable(
    d.object({
      environment_id: d.uuid,
      target_environment_id: d.uuid,
      fixture_service_id: d.uuid,
      target_service_id: d.uuid,
      target_project_id: d.uuid,
      target_organization_id: d.uuid,
      target_user_id: d.uuid,
      target_instance_id: d.identifier,
      target_build_digest: d.identifier,
      assets: d.array(d.object(scenarioAssets), 100),
    }),
  ),
  task_id: d.uuid,
  created_at: d.timestamp,
  updated_at: d.timestamp,
  actions: parseActions,
})
export const parseArtifact = d.object({
  id: d.uuid,
  sha256: digest,
  kind: d.choice([
    'manifest',
    'generation',
    'evidence',
    'verification',
    'junit',
    'execution_junit',
    'verification_junit',
    'cleanup',
  ] as const),
})
export const parseProposal = d.object({
  change_set_id: d.uuid,
  item_id: d.nullable(d.uuid),
  route: d.choice(['flow_spec_visual', 'controlled_write'] as const),
  content_fingerprint: digest,
  review_status: d.choice(['pending', 'accepted', 'rejected'] as const),
  materialized_resource_id: d.nullable(d.uuid),
})
export const parseHostEvidence = d.object({
  host: d.identifier,
  model: d.identifier,
  skill_digest: digest,
  prompt_digest: digest,
  authorized_budget_digest: digest,
  actual_tool_calls: (value: unknown) => {
    const count = d.positive(value)
    if (count > 100) throw new d.SelfTestContractError()
    return count
  },
})
const revisionDifference = d.object({
  path: (value: unknown) => {
    const path = d.boundedText(3, 4096)(value)
    if (!/^\$\.(workflow|case)/.test(path)) throw new d.SelfTestContractError()
    return path
  },
  before_digest: d.nullable(digest),
  after_digest: d.nullable(digest),
})
const assistedLineage = d.object({
  before_batch_id: d.uuid,
  origin_batch_id: d.uuid,
  before_source_digest: digest,
  before_workflow: publishedAsset,
  before_case: publishedAsset,
  before_workflow_proposal: parseProposal,
  before_case_proposal: parseProposal,
  editor_id: d.uuid,
  workflow_reviewer_id: d.uuid,
  case_reviewer_id: d.uuid,
  reason_digest: digest,
  diff_digest: digest,
  authorization_digest: digest,
  changes: d.nonEmptyArray(revisionDifference, 200),
  revision_number: (value: unknown) => {
    const revision = d.positive(value)
    if (revision > 20) throw new d.SelfTestContractError()
    return revision
  },
  review_mode: d.choice(['human', 'ci_fixture'] as const),
})
export const parseAssistedLineage = (value: unknown) => {
  const result = assistedLineage(value)
  if (
    new Set(result.changes.map((change) => change.path)).size !== result.changes.length ||
    result.changes.some((change) => change.before_digest === change.after_digest)
  ) {
    throw new d.SelfTestContractError()
  }
  return result
}
export const parseSource = d.object({
  host_evidence: d.optional(d.nullable(parseHostEvidence)),
  fixture_batch_key: d.optional(d.nullable(d.identifier)),
  assisted: d.optional(d.nullable(parseAssistedLineage)),
  ...scenarioAssets,
  design_fingerprint: digest,
  compilation_fingerprint: digest,
  oracle_mapping_digest: digest,
  workflow_proposal: parseProposal,
  case_proposal: parseProposal,
  api_sources_digest: digest,
  api_sources: d.nonEmptyArray(
    d.object({
      project_id: d.uuid,
      api_definition_id: d.uuid,
      api_version: d.positive,
      contract_fingerprint: digest,
    }),
    100,
  ),
  oracle_bindings: d.nonEmptyArray(
    d.object({
      oracle_id: d.identifier,
      node_id: d.identifier,
      phase: d.choice(['main', 'cleanup'] as const),
      expression: d.boundedText(1, 4096),
      expected_value_digest: digest,
      assertion_name: d.identifier,
    }),
    500,
  ),
  protocol_receipts_digest: digest,
  generation_manifest: parseArtifact,
})
export const parseGeneration = d.object({
  batch_id: d.uuid,
  generation_mode: d.nullable(generationMode),
  stage: generationStage,
  readiness,
  reason_codes: reasons,
  host_status: d.choice(['available', 'not_registered', 'expired'] as const),
  tool_call_count: d.integer,
  proposals: d.array(parseProposal, 100),
  sources: d.array(parseSource, 100),
  manifest: d.nullable(parseArtifact),
  actions: parseActions,
})
export const parseResourceSnapshot = d.object({
  suite: publishedAsset,
  plan_id: d.uuid,
  cases: d.nonEmptyArray(
    d.object({ ...scenarioAssets, environment_id: d.uuid, target_snapshot_digest: digest }),
    100,
  ),
})
const batchShape = d.object({
  id: d.uuid,
  installation_id: d.uuid,
  project_id: d.uuid,
  binding_id: d.uuid,
  batch_key: d.identifier,
  batch_kind: d.choice(['fixed_baseline', 'mcp_generated'] as const),
  generation_mode: d.nullable(generationMode),
  generation_stage: generationStage,
  readiness,
  reason_codes: reasons,
  phase: d.choice([
    'pending',
    'generating',
    'awaiting_review',
    'ready',
    'running',
    'collecting',
    'completed',
    'cancelled',
    'expired',
  ] as const),
  revision: d.integer,
  verdict: d.choice(['pending', 'passed', 'failed', 'blocked'] as const),
  sealed_verdict: d.optional(d.nullable(d.choice(['passed', 'failed', 'blocked'] as const))),
  verification_scope: d.choice(['full_pack', 'selected_suites', 'diagnostic_subset'] as const),
  provenance: d.choice(['local_untrusted', 'trusted_ci'] as const),
  evidence_integrity: d.choice(['complete', 'missing', 'expired'] as const),
  cleanup_status: d.choice(['pending', 'completed', 'failed', 'needs_review'] as const),
  expected_count: d.positive,
  expected_scenario_set: d.array(d.object(scenarioKey), 100),
  required_scenario_set: d.array(d.object(scenarioKey), 100),
  manifest_digest: digest,
  resource_digest: d.nullable(digest),
  policy_digest: digest,
  binding_fingerprint: digest,
  environment_fingerprint: digest,
  builds: parseBuilds,
  deadline: d.timestamp,
  created_at: d.timestamp,
  updated_at: d.timestamp,
  sealed_at: d.nullable(d.timestamp),
  plan_run_ids: d.array(d.uuid, 100),
  plan_id: d.optional(d.nullable(d.uuid)),
  suite: d.optional(d.nullable(publishedAsset)),
  resource_snapshot: d.optional(d.nullable(parseResourceSnapshot)),
  artifacts: d.array(parseArtifact, 100),
  actions: parseActions,
})
export function parseBatch(value: unknown) {
  const result = batchShape(value)
  const expected = result.expected_scenario_set.map(
    (item) => `${item.scenario_id}:${item.variant_key}`,
  )
  const required = result.required_scenario_set.map(
    (item) => `${item.scenario_id}:${item.variant_key}`,
  )
  if (
    !required.length ||
    result.expected_count !== expected.length ||
    new Set(expected).size !== expected.length ||
    new Set(required).size !== required.length ||
    required.some((id) => !expected.includes(id)) ||
    (result.batch_kind === 'mcp_generated') !== (result.generation_mode !== null)
  )
    throw new d.SelfTestContractError()
  validateResourceSnapshot(result)
  return result
}
function validateResourceSnapshot(batch: ReturnType<typeof batchShape>) {
  const snapshot = batch.resource_snapshot
  if (!snapshot) return
  const expected = batch.expected_scenario_set
    .map((item) => `${item.scenario_id}:${item.variant_key}`)
    .sort()
  const actual = snapshot.cases.map((item) => `${item.scenario_id}:${item.variant_key}`).sort()
  if (JSON.stringify(expected) !== JSON.stringify(actual)) throw new d.SelfTestContractError()
  if (batch.plan_id && batch.plan_id !== snapshot.plan_id) throw new d.SelfTestContractError()
  if (batch.suite && JSON.stringify(batch.suite) !== JSON.stringify(snapshot.suite))
    throw new d.SelfTestContractError()
}
export const parseScenario = d.object({
  ...scenarioKey,
  id: d.uuid,
  batch_id: d.uuid,
  title: d.identifier,
  category: d.choice(['api', 'engine', 'mcp'] as const),
  expected: expectedResult,
  observed_status: d.nullable(
    d.choice(['queued', 'running', 'passed', 'failed', 'cancelled', 'quarantined'] as const),
  ),
  verification_status: verification,
  reason_codes: reasons,
  generation_attempt: d.integer,
  source: d.nullable(parseSource),
  published_assets: d.nullable(d.object(scenarioAssets)),
  executions: d.array(
    d.object({
      test_plan_run_id: d.uuid,
      run_item_id: d.uuid,
      execution_id: d.nullable(d.uuid),
      target_version: d.positive,
      target_snapshot_digest: d.optional(d.nullable(digest)),
    }),
    20,
  ),
  evidence_refs: d.array(parseArtifact, 30),
  attempts_complete: d.bool,
})
export const parseRelation = d.object({
  batch: parseBatch,
  scenario: parseScenario,
  execution_id: d.uuid,
})
export function pageOf<T>(decode: d.Decoder<T>) {
  return d.object({
    items: d.array(decode, 100),
    next_cursor: d.nullable(d.uuid),
    has_more: d.bool,
    total: d.integer,
    truncated: d.bool,
  })
}
export type SelfTestPage<T> = {
  items: T[]
  next_cursor: string | null
  has_more: boolean
  total: number
  truncated: boolean
}
export type SelfTestTemplate = ReturnType<typeof parseTemplate>
export type SelfTestBinding = ReturnType<typeof parseBinding>
export type SelfTestPreview = ReturnType<typeof parsePreview>
export type SelfTestInstallation = ReturnType<typeof parseInstallation>
export type SelfTestBatch = ReturnType<typeof parseBatch>
export type SelfTestGeneration = ReturnType<typeof parseGeneration>
export type SelfTestScenario = ReturnType<typeof parseScenario>
export type SelfTestSource = ReturnType<typeof parseSource>
export type SelfTestArtifact = ReturnType<typeof parseArtifact>
export type SelfTestProposal = ReturnType<typeof parseProposal>
export type SelfTestRelation = ReturnType<typeof parseRelation>
export type SelfTestBudget = {
  timeout_seconds: number
  max_requests: number
  max_tool_calls: number
}
export type PreviewInput = {
  template_id: SelfTestTemplate['id']
  template_version: string
  binding_id: string
}
export type InstallInput = PreviewInput & {
  preview_fingerprint: string
  preview_expires_at: string
}
export type BatchInput = {
  scenario_ids: string[]
  verification_scope: SelfTestBatch['verification_scope']
  budget: SelfTestBudget
}
export type GenerationInput = BatchInput & {
  generation_mode: NonNullable<SelfTestBatch['generation_mode']>
  host_id: null
}
export type ExecuteInput = {
  resource_digest: string
  environment_fingerprint: string
  confirmed: true
}
