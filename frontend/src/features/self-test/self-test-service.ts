import type { AxiosResponseTransformer } from 'axios'
import { apiClient } from '../../lib/api'
import { SelfTestContractError } from './self-test-decode'
import {
  pageOf,
  parseBatch,
  parseBinding,
  parseGeneration,
  parseInstallation,
  parsePreview,
  parseRelation,
  parseScenario,
  parseTemplate,
  type BatchInput,
  type ExecuteInput,
  type GenerationInput,
  type InstallInput,
  type PreviewInput,
  type SelfTestArtifact,
} from './self-test-contract'

const root = (projectId: string) => `/projects/${encodeURIComponent(projectId)}/self-tests`
const run = (projectId: string, batchId: string) =>
  `${root(projectId)}/runs/${encodeURIComponent(batchId)}`
const keyHeader = (idempotencyKey: string) => ({ headers: { 'Idempotency-Key': idempotencyKey } })

export async function listSelfTestTemplates(projectId: string, signal?: AbortSignal) {
  return pageOf(parseTemplate)(
    (await apiClient.get<unknown>(`${root(projectId)}/templates`, { signal })).data,
  )
}
export async function listSelfTestBindings(projectId: string, signal?: AbortSignal) {
  return pageOf(parseBinding)(
    (await apiClient.get<unknown>(`${root(projectId)}/bindings`, { signal })).data,
  )
}
export async function previewSelfTestInstallation(projectId: string, input: PreviewInput) {
  const result = parsePreview(
    (await apiClient.post<unknown>(`${root(projectId)}/installations/preview`, input)).data,
  )
  if (
    result.binding_id !== input.binding_id ||
    result.template.id !== input.template_id ||
    result.template.version !== input.template_version
  )
    throw new SelfTestContractError()
  return result
}
export async function installSelfTest(projectId: string, input: InstallInput, key: string) {
  const result = parseInstallation(
    (await apiClient.post<unknown>(`${root(projectId)}/installations`, input, keyHeader(key))).data,
  )
  if (
    result.project_id !== projectId ||
    result.binding_id !== input.binding_id ||
    result.template_id !== input.template_id
  )
    throw new SelfTestContractError()
  return result
}
export async function getSelfTestInstallation(projectId: string, id: string, signal?: AbortSignal) {
  const result = parseInstallation(
    (
      await apiClient.get<unknown>(`${root(projectId)}/installations/${encodeURIComponent(id)}`, {
        signal,
      })
    ).data,
  )
  if (result.id !== id || result.project_id !== projectId) throw new SelfTestContractError()
  return result
}
export async function listSelfTestRuns(
  projectId: string,
  installationId: string,
  cursor: string | null,
  signal?: AbortSignal,
) {
  const result = pageOf(parseBatch)(
    (
      await apiClient.get<unknown>(
        `${root(projectId)}/installations/${encodeURIComponent(installationId)}/runs`,
        { params: { cursor: cursor ?? undefined, page_size: 20 }, signal },
      )
    ).data,
  )
  if (
    result.items.some(
      (item) => item.project_id !== projectId || item.installation_id !== installationId,
    ) ||
    (result.has_more && !result.next_cursor)
  )
    throw new SelfTestContractError()
  return result
}
export async function getSelfTestBatch(projectId: string, id: string, signal?: AbortSignal) {
  const result = parseBatch((await apiClient.get<unknown>(run(projectId, id), { signal })).data)
  if (result.id !== id || result.project_id !== projectId) throw new SelfTestContractError()
  return result
}
export async function getSelfTestGeneration(projectId: string, id: string, signal?: AbortSignal) {
  const result = parseGeneration(
    (await apiClient.get<unknown>(`${run(projectId, id)}/generation`, { signal })).data,
  )
  if (result.batch_id !== id) throw new SelfTestContractError()
  return result
}
export async function listSelfTestScenarios(
  projectId: string,
  id: string,
  filters: { page: number; category: string; verification: string; scenarioId: string | null },
  signal?: AbortSignal,
) {
  const result = pageOf(parseScenario)(
    (
      await apiClient.get<unknown>(`${run(projectId, id)}/scenarios`, {
        params: {
          page: filters.page,
          page_size: 20,
          category: filters.category || undefined,
          verification: filters.verification || undefined,
          scenario_id: filters.scenarioId ?? undefined,
        },
        signal,
      })
    ).data,
  )
  if (
    result.items.some((item) => item.batch_id !== id) ||
    result.items.some((item) => filters.scenarioId && item.scenario_id !== filters.scenarioId) ||
    new Set(result.items.map((item) => item.id)).size !== result.items.length
  )
    throw new SelfTestContractError()
  return result
}
export async function createSelfTestRun(
  projectId: string,
  installationId: string,
  input: BatchInput,
  key: string,
) {
  const result = parseBatch(
    (
      await apiClient.post<unknown>(
        `${root(projectId)}/installations/${encodeURIComponent(installationId)}/runs`,
        input,
        keyHeader(key),
      )
    ).data,
  )
  if (
    result.project_id !== projectId ||
    result.installation_id !== installationId ||
    result.batch_kind !== 'fixed_baseline'
  )
    throw new SelfTestContractError()
  return result
}
export async function createGenerationBatch(
  projectId: string,
  installationId: string,
  input: GenerationInput,
  key: string,
) {
  const result = parseBatch(
    (
      await apiClient.post<unknown>(
        `${root(projectId)}/installations/${encodeURIComponent(installationId)}/generation-batches`,
        input,
        keyHeader(key),
      )
    ).data,
  )
  if (
    result.project_id !== projectId ||
    result.installation_id !== installationId ||
    result.batch_kind !== 'mcp_generated' ||
    result.generation_mode !== input.generation_mode
  )
    throw new SelfTestContractError()
  return result
}
export async function executeSelfTestAssets(
  projectId: string,
  batchId: string,
  input: ExecuteInput,
  key: string,
) {
  const result = parseBatch(
    (
      await apiClient.post<unknown>(
        `${run(projectId, batchId)}/execute-materialized`,
        input,
        keyHeader(key),
      )
    ).data,
  )
  if (result.project_id !== projectId || result.id !== batchId) throw new SelfTestContractError()
  return result
}
export async function cancelSelfTestBatch(projectId: string, batchId: string, key: string) {
  const result = parseBatch(
    (await apiClient.post<unknown>(`${run(projectId, batchId)}/cancel`, {}, keyHeader(key))).data,
  )
  if (result.project_id !== projectId || result.id !== batchId) throw new SelfTestContractError()
  return result
}
export async function getSelfTestExecutionRelation(
  projectId: string,
  batchId: string,
  scenarioId: string,
  executionId: string,
  signal?: AbortSignal,
) {
  const result = parseRelation(
    (
      await apiClient.get<unknown>(
        `${run(projectId, batchId)}/scenarios/${encodeURIComponent(scenarioId)}/executions/${encodeURIComponent(executionId)}`,
        { signal },
      )
    ).data,
  )
  if (
    result.batch.id !== batchId ||
    result.batch.project_id !== projectId ||
    result.scenario.batch_id !== batchId ||
    result.scenario.scenario_id !== scenarioId ||
    result.execution_id !== executionId ||
    !result.scenario.executions.some((item) => item.execution_id === executionId)
  )
    throw new SelfTestContractError()
  return result
}
const artifactResponse: AxiosResponseTransformer = (data: unknown, _headers, status) => {
  if (typeof status === 'number' && status >= 400 && data instanceof ArrayBuffer)
    return JSON.parse(new TextDecoder().decode(data)) as unknown
  return data
}
export async function readSelfTestArtifact(
  projectId: string,
  batchId: string,
  artifact: SelfTestArtifact,
): Promise<Blob> {
  const response = await apiClient.get<ArrayBuffer>(
    `${run(projectId, batchId)}/artifacts/${encodeURIComponent(artifact.id)}`,
    { responseType: 'arraybuffer', transformResponse: [artifactResponse] },
  )
  if (!(response.data instanceof ArrayBuffer)) throw new SelfTestContractError()
  if (response.data.byteLength > 8 * 1024 * 1024) throw new Error('自测证据超过允许的下载大小。')
  const contentType: unknown = response.headers['content-type']
  return new Blob([response.data], {
    type: typeof contentType === 'string' ? contentType : 'application/octet-stream',
  })
}
