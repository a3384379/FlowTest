import { reportExecutionPath, type ExecutionLocation } from '../workflows/execution-navigation'

export type SelfTestMode = 'mcp_generation' | 'native'
export type VerificationStatus =
  'pending' | 'matched' | 'mismatched' | 'incomplete' | 'error' | 'unsupported'
export type SelfTestReference = { batchId: string; scenarioId?: string }
export type SelfTestPanel = 'provenance' | 'verification'
const uuid = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i
const scenario = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$/
const verificationStates = [
  'pending',
  'matched',
  'mismatched',
  'incomplete',
  'error',
  'unsupported',
]

export function selfTestLocation(params: URLSearchParams) {
  const ids = ['binding', 'installation', 'batch', 'cursor'] as const
  const invalidId = ids.some((key) => params.has(key) && !uuid.test(params.get(key)!))
  const page = Number(params.get('page') ?? '1')
  const verification = params.get('verification') ?? ''
  const category = params.get('category') ?? ''
  const scenarioId = params.get('scenario')
  const invalid = invalidLocation({ invalidId, page, verification, category, scenarioId })
  return {
    active: params.get('tab') === 'selftest',
    mode: (params.get('mode') === 'native' ? 'native' : 'mcp_generation') as SelfTestMode,
    bindingId: params.get('binding'),
    installationId: params.get('installation'),
    batchId: params.get('batch'),
    scenarioId,
    page: invalid ? 1 : page,
    verification: verification as VerificationStatus | '',
    category,
    error: invalid ? 'URL 中的自测范围、对象标识或页码无效，请核对链接。' : null,
  }
}

export function reportSelfTestReference(params: URLSearchParams): SelfTestReference | null {
  const batchId = params.get('selfTestBatch')
  const scenarioId = params.get('selfTestScenario')
  if (!batchId || !uuid.test(batchId) || (scenarioId && !scenario.test(scenarioId))) return null
  return { batchId, ...(scenarioId ? { scenarioId } : {}) }
}

export function selfTestPath(
  projectId: string,
  reference?: SelfTestReference,
  mode: SelfTestMode = 'mcp_generation',
): string {
  const params = new URLSearchParams({ tab: 'selftest', mode })
  if (reference) {
    params.set('batch', reference.batchId)
    if (reference.scenarioId) params.set('scenario', reference.scenarioId)
  }
  return `/projects/${projectId}/quality?${params}`
}

export function selfTestReportPath(
  projectId: string,
  location: ExecutionLocation,
  reference: SelfTestReference,
  panel: SelfTestPanel = 'verification',
): string {
  const path = reportExecutionPath(projectId, location)
  const [pathname, search] = path.split('?')
  const params = new URLSearchParams(search)
  params.set('selfTestBatch', reference.batchId)
  if (reference.scenarioId) params.set('selfTestScenario', reference.scenarioId)
  params.set('panel', panel)
  return `${pathname}?${params}`
}

export function clearSelfTestReference(params: URLSearchParams): void {
  for (const name of ['selfTestBatch', 'selfTestScenario', 'panel']) params.delete(name)
}

export function selfTestProposalPath(
  projectId: string,
  kind: 'flow_spec' | 'controlled_write',
  proposalId: string,
  reference: SelfTestReference,
): string {
  const params = new URLSearchParams({ [kind === 'flow_spec' ? 'proposal' : 'focus']: proposalId })
  params.set('selfTestBatch', reference.batchId)
  if (reference.scenarioId) params.set('selfTestScenario', reference.scenarioId)
  return `/projects/${projectId}/${kind === 'flow_spec' ? 'workflows' : 'mcp-changes'}?${params}`
}

function invalidLocation({
  invalidId,
  page,
  verification,
  category,
  scenarioId,
}: {
  invalidId: boolean
  page: number
  verification: string
  category: string
  scenarioId: string | null
}) {
  return (
    invalidId ||
    !Number.isSafeInteger(page) ||
    page < 1 ||
    page > 1000 ||
    (verification !== '' && !verificationStates.includes(verification)) ||
    (category !== '' && !['api', 'engine', 'mcp'].includes(category)) ||
    (scenarioId !== null && !scenario.test(scenarioId))
  )
}
