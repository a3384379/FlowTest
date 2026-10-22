import { useCatalogQuery } from '../../lib/catalog-query'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { App } from 'antd'
import { useEffect, useLayoutEffect, useRef } from 'react'

import { apiErrorWithTrace, SessionBoundaryError } from '../../lib/api'
import { useRouteScopedSelection } from '../../lib/use-route-scoped-state'
import { listImpactRuns } from '../impact/impact-service'
import { useProjectContext } from '../projects/use-project-context'
import { useProjectCapabilities } from '../projects/use-project-capabilities'
import { listReleaseRisks } from '../quality/quality-service'
import { getV3FeatureFlags } from '../capabilities/capability-service'
import { getAIStatus } from './ai-service'
import {
  createAIChangeSet,
  getAIChangeSet,
  listAIChangeSets,
  reviewAIChangeItem,
  type AIChangeSetInput,
  type AIChangeItem,
} from './ai-change-set-service'

export function useAIChangeSets(initialChangeSetId: string | null = null) {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const { projectId } = useProjectContext()
  const { canEdit, permissions } = useProjectCapabilities()
  const { flags, status, impacts, risks } = useAIChangeSources(projectId)
  const [selection, setSelection] = useRouteScopedSelection(projectId, initialChangeSetId)
  const canReview = canWrite(canEdit, status.data?.enabled, flags.data?.quality_intelligence)
  const polling = canWrite(true, status.data?.enabled, flags.data?.quality_intelligence)
  const { changeSets, detail, activeId } = useAIChangeRecords(projectId, selection, polling)
  const canCreate = canReview && flags.data?.impact_engine === true
  const scope = `${projectId}:${activeId}:${initialChangeSetId}`
  const current = useRef(scope)
  useLayoutEffect(() => {
    current.current = scope
  }, [scope])
  const pending = useRef(false)
  const alive = useRef(true)
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])
  const create = useMutation({ mutationFn: createAIChangeSet })
  const review = useMutation({
    mutationFn: ({
      itemId,
      decision,
      content,
      note,
      changeSetId,
    }: {
      itemId: string
      decision: 'accept' | 'reject'
      content?: Record<string, unknown>
      note: string
      project: string
      changeSetId: string
      resourceType: AIChangeItem['item_type']
    }) => reviewAIChangeItem(changeSetId, itemId, decision, { content, note }),
    onSuccess: async (result, { project, changeSetId, decision }) => {
      if (decision === 'accept')
        await invalidateDraft(queryClient, project, result.materialized_resource_type)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['ai-change-set', project, changeSetId] }),
        queryClient.invalidateQueries({ queryKey: ['ai-change-sets', project] }),
      ])
    },
    onError: async (error, { project, changeSetId, decision, resourceType }) => {
      if (!(error instanceof SessionBoundaryError)) return
      await Promise.all([
        decision === 'accept'
          ? invalidateDraft(queryClient, project, resourceType, 'none')
          : Promise.resolve(),
        queryClient.invalidateQueries({
          queryKey: ['ai-change-set', project, changeSetId],
          refetchType: 'none',
        }),
        queryClient.invalidateQueries({
          queryKey: ['ai-change-sets', project],
          refetchType: 'none',
        }),
      ])
    },
  })

  async function addChangeSet(input: Omit<AIChangeSetInput, 'project_id'>) {
    if (!canCreate || pending.current) return false
    pending.current = true
    try {
      const created = await create.mutateAsync({ ...input, project_id: required(projectId) })
      await queryClient.invalidateQueries({ queryKey: ['ai-change-sets', projectId] })
      if (!alive.current || current.current !== scope) return false
      setSelection(created.id)
      void message.success('AI Draft Change Set 已提交生成')
      return true
    } catch (error) {
      void queryClient.invalidateQueries({ queryKey: ['ai-change-sets', projectId] })
      if (alive.current && current.current === scope) void message.error(apiErrorWithTrace(error))
      return false
    } finally {
      pending.current = false
    }
  }

  async function reviewItem(
    itemId: string,
    decision: 'accept' | 'reject',
    content: Record<string, unknown> | undefined,
    note: string,
  ) {
    const item = reviewableItem(canReview, pending.current, detail.data, itemId)
    if (!item) return false
    pending.current = true
    try {
      await review.mutateAsync({
        itemId,
        decision,
        content,
        note,
        project: required(projectId),
        changeSetId: required(activeId),
        resourceType: item.item_type,
      })
      if (!alive.current || current.current !== scope) return false
      void message.success(decision === 'accept' ? '变更项已接受并生成草稿' : '变更项已拒绝')
      return true
    } catch (error) {
      if (alive.current && current.current === scope) void message.error(apiErrorWithTrace(error))
      return false
    } finally {
      pending.current = false
    }
  }

  return {
    projectId,
    canEdit,
    canCreate,
    canReview,
    reviewError: review.error ? apiErrorWithTrace(review.error) : '',
    clearReviewError: review.reset,
    permissions,
    flags,
    status,
    changeSets,
    detail,
    impacts,
    risks,
    activeId,
    select: setSelection,
    addChangeSet,
    reviewItem,
    creating: create.isPending,
    reviewing: review.isPending,
  }
}

function useAIChangeSources(projectId: string | null) {
  const flags = useQuery({ queryKey: ['v3-feature-flags'], queryFn: getV3FeatureFlags })
  const status = useQuery({
    queryKey: ['ai-status', projectId],
    queryFn: () => getAIStatus(required(projectId)),
    enabled: Boolean(projectId),
  })
  const impacts = useCatalogQuery(
    'impact-runs',
    projectId,
    (page) => listImpactRuns(required(projectId), page, 20),
    Boolean(projectId && flags.data?.impact_engine),
    '',
    {},
  )
  const risks = useCatalogQuery(
    'release-risks',
    projectId,
    (page) => listReleaseRisks(required(projectId), page, 20),
    Boolean(projectId && flags.data?.quality_intelligence),
    '',
    {},
  )
  return { flags, status, impacts, risks }
}

function required(value: string | null): string {
  if (!value) throw new Error('请选择项目')
  return value
}

function canWrite(
  canEdit: boolean,
  aiEnabled: boolean | undefined,
  qualityEnabled: boolean | undefined,
): boolean {
  return canEdit && aiEnabled === true && qualityEnabled === true
}
async function invalidateDraft(
  client: ReturnType<typeof useQueryClient>,
  projectId: string | null,
  type: string | null,
  refetchType: 'active' | 'none' = 'active',
) {
  const keys =
    type === 'test_case'
      ? [
          'test-cases',
          'test-asset',
          'test-case-versions',
          'test-case-options',
          'asset-directory-counts',
        ]
      : ['workflows', 'workflow', 'workflow-versions']
  await Promise.all(
    keys.map((key) => client.invalidateQueries({ queryKey: [key, projectId], refetchType })),
  )
}

function useAIChangeRecords(projectId: string | null, selection: string | null, polling: boolean) {
  const changeSets = useCatalogQuery(
    'ai-change-sets',
    projectId,
    (page) => listAIChangeSets(required(projectId), page, 20),
    Boolean(projectId),
    '',
    {
      refetchInterval: (query) =>
        polling && query.state.data?.items.some((item) => item.status === 'generating')
          ? 1_000
          : false,
    },
  )
  const currentItems = changeSets.data?.items.filter((item) => item.project_id === projectId) ?? []
  const activeId = selection ?? currentItems.at(0)?.id ?? null
  const detail = useQuery({
    queryKey: ['ai-change-set', projectId, activeId],
    queryFn: async () => {
      const result = await getAIChangeSet(required(activeId))
      if (result.project_id !== projectId) throw new Error('该变更集不属于当前项目')
      return result
    },
    enabled: Boolean(projectId && activeId),
    refetchInterval: (query) =>
      polling && query.state.data?.status === 'generating' ? 1_000 : false,
  })
  return { changeSets, detail, activeId }
}

function reviewableItem(
  allowed: boolean,
  pending: boolean,
  detail: import('./ai-change-set-service').AIChangeSetDetail | undefined,
  itemId: string,
): AIChangeItem | undefined {
  if (!allowed || pending) return undefined
  return detail?.items.find((item) => item.id === itemId && item.review_status === 'pending')
}
