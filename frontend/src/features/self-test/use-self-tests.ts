import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { useProjectContext } from '../projects/use-project-context'
import { useProjectCapabilities } from '../projects/use-project-capabilities'
import { useQueryInvalidated } from '../../lib/use-query-invalidated'
import { selfTestLocation } from './self-test-navigation'
import { selfTestKeys, useSelfTestIdentity, type SelfTestIdentity } from './self-test-query-keys'
import * as api from './self-test-service'
import type { SelfTestBatch } from './self-test-contract'
import { isDispatchRecovery } from './self-test-dispatch-recovery'

type Context = {
  identity: SelfTestIdentity
  projectId: string
  enabled: boolean
  location: ReturnType<typeof selfTestLocation>
}
export function batchIsActive(batch: SelfTestBatch | undefined) {
  return Boolean(batch && !['completed', 'cancelled', 'expired'].includes(batch.phase))
}
function useCatalogs(context: Context) {
  const { identity, projectId, enabled } = context
  const templates = useQuery({
    queryKey: selfTestKeys.templates(identity),
    queryFn: ({ signal }) => api.listSelfTestTemplates(projectId, signal),
    enabled,
  })
  const bindingsKey = selfTestKeys.bindings(identity)
  const bindingsInvalidated = useQueryInvalidated(bindingsKey)
  const bindings = useQuery({
    queryKey: bindingsKey,
    queryFn: ({ signal }) => api.listSelfTestBindings(projectId, signal),
    enabled,
  })
  const binding = bindings.isSuccess
    ? bindings.data.items.find((item) => item.id === context.location.bindingId)
    : undefined
  return { templates, bindings, bindingsInvalidated, binding }
}
function useInstallation(context: Context, cursor: string | null) {
  const { identity, projectId, location, enabled } = context
  const installationKey = selfTestKeys.installation(identity, location.installationId)
  const installationInvalidated = useQueryInvalidated(installationKey)
  const installation = useQuery({
    queryKey: installationKey,
    queryFn: ({ signal }) =>
      api.getSelfTestInstallation(projectId, location.installationId!, signal),
    enabled: enabled && Boolean(location.installationId),
    refetchInterval: (query) =>
      query.state.data && ['needs_input', 'queued', 'installing'].includes(query.state.data.status)
        ? 2000
        : false,
    refetchIntervalInBackground: false,
  })
  const runs = useQuery({
    queryKey: selfTestKeys.runs(identity, location.installationId, cursor),
    queryFn: ({ signal }) =>
      api.listSelfTestRuns(projectId, location.installationId!, cursor, signal),
    enabled: enabled && installation.isSuccess,
  })
  return {
    installation,
    installationInvalidated,
    runs,
    selectedInstallation: installation.isSuccess ? installation.data : undefined,
  }
}
function useBatch(context: Context) {
  const { identity, projectId, location, enabled } = context
  const batchKey = selfTestKeys.batch(identity, location.batchId)
  const batchInvalidated = useQueryInvalidated(batchKey)
  const batch = useQuery({
    queryKey: batchKey,
    queryFn: ({ signal }) => api.getSelfTestBatch(projectId, location.batchId!, signal),
    enabled: enabled && Boolean(location.batchId),
    refetchInterval: (query) => (batchIsActive(query.state.data) ? 2000 : false),
    refetchIntervalInBackground: false,
  })
  const selectedBatch = batch.isSuccess ? batch.data : undefined
  const generation = useQuery({
    queryKey: selfTestKeys.generation(identity, location.batchId),
    queryFn: ({ signal }) => api.getSelfTestGeneration(projectId, location.batchId!, signal),
    enabled: enabled && selectedBatch?.batch_kind === 'mcp_generated',
    refetchInterval: batchIsActive(selectedBatch) ? 2000 : false,
    refetchIntervalInBackground: false,
  })
  const filters = {
    page: location.page,
    category: location.category,
    verification: location.verification,
    scenarioId: location.scenarioId,
  }
  const scenarios = useQuery({
    queryKey: [
      ...selfTestKeys.scenarios(identity, location.batchId, filters),
      selectedBatch?.revision ?? null,
    ],
    queryFn: ({ signal }) =>
      api.listSelfTestScenarios(projectId, location.batchId!, filters, signal),
    enabled: enabled && batch.isSuccess,
    refetchInterval: batchIsActive(selectedBatch) ? 2000 : false,
    refetchIntervalInBackground: false,
  })
  return { batch, batchInvalidated, selectedBatch, generation, scenarios }
}
function batchScopeMismatch(context: Context, batch: SelfTestBatch | undefined) {
  if (!batch) return false
  const { location } = context
  if (location.installationId && batch.installation_id !== location.installationId) return true
  if (location.bindingId && batch.binding_id !== location.bindingId) return true
  return (batch.batch_kind === 'fixed_baseline') !== (location.mode === 'native')
}
function selectionMismatch(
  context: Context,
  installation: ReturnType<typeof useInstallation>,
  batch: ReturnType<typeof useBatch>,
) {
  if (batchScopeMismatch(context, batch.selectedBatch)) return true
  const selected = installation.selectedInstallation
  return Boolean(
    selected && context.location.bindingId && selected.binding_id !== context.location.bindingId,
  )
}
function useAuthority(
  catalogs: ReturnType<typeof useCatalogs>,
  installation: ReturnType<typeof useInstallation>,
  batches: ReturnType<typeof useBatch>,
  scopeMismatch: boolean,
) {
  const capabilities = useProjectCapabilities()
  const freshBinding = [
    !catalogs.bindingsInvalidated,
    catalogs.bindings.isSuccess,
    Boolean(catalogs.binding),
  ].every(Boolean)
  const freshInstallation = [
    !installation.installationInvalidated,
    installation.installation.isSuccess,
    !scopeMismatch,
  ].every(Boolean)
  const freshBatch = [!batches.batchInvalidated, batches.batch.isSuccess, !scopeMismatch].every(
    Boolean,
  )
  const bindingActions = availableActions(catalogs.binding)
  const installActions = availableActions(installation.selectedInstallation)
  const batchActions = availableActions(batches.selectedBatch)
  return {
    permissions: capabilities.permissions,
    executeAllowed: capabilities.canExecute,
    canInitialize: [capabilities.canEdit, freshBinding, bindingActions.can_initialize].every(
      Boolean,
    ),
    canGenerate: [
      capabilities.canEdit,
      freshBinding,
      freshInstallation,
      bindingActions.can_generate,
      installActions.can_generate,
    ].every(Boolean),
    canRun: [
      capabilities.canExecute,
      freshBinding,
      freshInstallation,
      bindingActions.can_execute,
      installActions.can_execute,
    ].every(Boolean),
    canExecute: [
      capabilities.canExecute,
      freshBinding,
      freshInstallation,
      freshBatch,
      bindingActions.can_execute,
      batchActions.can_execute,
      batches.selectedBatch?.phase === 'ready' || isDispatchRecovery(batches.selectedBatch),
      Boolean(batches.selectedBatch?.resource_snapshot),
      publishedSourcesReady(batches),
    ].every(Boolean),
    canCancel: [capabilities.canExecute, freshBatch, batchActions.can_cancel].every(Boolean),
  }
}
export function useSelfTests() {
  const { projectId } = useProjectContext()
  const identity = useSelfTestIdentity(projectId)
  const [params, setParams] = useSearchParams()
  const location = selfTestLocation(params)
  const context = {
    projectId: projectId!,
    identity,
    location,
    enabled: Boolean(projectId && identity.userId && !location.error),
  }
  const catalogs = useCatalogs(context)
  const installation = useInstallation(context, params.get('cursor'))
  const batches = useBatch(context)
  const scopeMismatch = selectionMismatch(context, installation, batches)
  const authority = useAuthority(catalogs, installation, batches, scopeMismatch)
  function select(values: Record<string, string | null>) {
    const next = new URLSearchParams(params)
    next.set('tab', 'selftest')
    for (const [key, value] of Object.entries(values)) {
      if (value === null) next.delete(key)
      else next.set(key, value)
    }
    setParams(next)
  }
  return {
    projectId,
    identity,
    location,
    ...catalogs,
    ...installation,
    ...batches,
    ...authority,
    scopeMismatch,
    select,
  }
}
export type SelfTestState = ReturnType<typeof useSelfTests>

function availableActions(
  value: { actions: import('./self-test-contract').SelfTestBinding['actions'] } | undefined,
) {
  return (
    value?.actions ?? {
      can_initialize: false,
      can_generate: false,
      can_execute: false,
      can_cancel: false,
      reason_codes: [],
    }
  )
}

function publishedSourcesReady(batches: ReturnType<typeof useBatch>) {
  const batch = batches.selectedBatch
  if (batch?.batch_kind === 'fixed_baseline') return isDispatchRecovery(batch)
  if (!batch || !batches.generation.isSuccess) return false
  const generation = batches.generation.data
  if (generation.stage !== 'ready' || generation.readiness !== 'ready') return false
  const expected = batch.expected_scenario_set
    .map((item) => `${item.scenario_id}:${item.variant_key}`)
    .sort()
  const actual = generation.sources.map((item) => `${item.scenario_id}:${item.variant_key}`).sort()
  return JSON.stringify(expected) === JSON.stringify(actual)
}
