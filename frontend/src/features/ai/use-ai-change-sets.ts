import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { App } from 'antd'

import { apiErrorMessage } from '../../lib/api'
import { useRouteScopedSelection } from '../../lib/use-route-scoped-state'
import { listImpactRuns } from '../impact/impact-service'
import { useProjectContext } from '../projects/use-project-context'
import { listReleaseRisks } from '../quality/quality-service'
import {
  createAIChangeSet,
  getAIChangeSet,
  listAIChangeSets,
  reviewAIChangeItem,
  type AIChangeSetInput,
} from './ai-change-set-service'

export function useAIChangeSets(initialChangeSetId: string | null = null) {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const { projectId } = useProjectContext()
  const [selection, setSelection] = useRouteScopedSelection(projectId, initialChangeSetId)
  const changeSets = useQuery({
    queryKey: ['ai-change-sets', projectId],
    queryFn: () => listAIChangeSets(required(projectId)),
    enabled: Boolean(projectId),
    refetchInterval: (query) =>
      query.state.data?.items.some((item) => item.status === 'generating') ? 1_000 : false,
  })
  const currentItems = changeSets.data?.items.filter((item) => item.project_id === projectId) ?? []
  const activeId = selection ?? currentItems.at(0)?.id ?? null
  const detail = useQuery({
    queryKey: ['ai-change-set', projectId, activeId],
    queryFn: () => getAIChangeSet(required(activeId)),
    enabled: Boolean(projectId && activeId),
    refetchInterval: (query) => (query.state.data?.status === 'generating' ? 1_000 : false),
  })
  const impacts = useQuery({
    queryKey: ['impact-runs', projectId],
    queryFn: () => listImpactRuns(required(projectId)),
    enabled: Boolean(projectId),
  })
  const risks = useQuery({
    queryKey: ['release-risks', projectId],
    queryFn: () => listReleaseRisks(required(projectId)),
    enabled: Boolean(projectId),
  })
  const create = useMutation({ mutationFn: createAIChangeSet })
  const review = useMutation({
    mutationFn: ({
      itemId,
      decision,
      content,
      note,
    }: {
      itemId: string
      decision: 'accept' | 'reject'
      content?: Record<string, unknown>
      note: string
    }) => reviewAIChangeItem(required(activeId), itemId, decision, { content, note }),
  })

  async function addChangeSet(input: Omit<AIChangeSetInput, 'project_id'>) {
    try {
      const created = await create.mutateAsync({ ...input, project_id: required(projectId) })
      setSelection(created.id)
      await queryClient.invalidateQueries({ queryKey: ['ai-change-sets', projectId] })
      void message.success('AI Draft Change Set 已提交生成')
      return true
    } catch (error) {
      void message.error(apiErrorMessage(error))
      return false
    }
  }

  async function reviewItem(
    itemId: string,
    decision: 'accept' | 'reject',
    content: Record<string, unknown> | undefined,
    note: string,
  ) {
    try {
      await review.mutateAsync({ itemId, decision, content, note })
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['ai-change-set', projectId, activeId] }),
        queryClient.invalidateQueries({ queryKey: ['ai-change-sets', projectId] }),
      ])
      void message.success(decision === 'accept' ? '变更项已接受并生成草稿' : '变更项已拒绝')
      return true
    } catch (error) {
      void message.error(apiErrorMessage(error))
      return false
    }
  }

  return {
    projectId,
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

function required(value: string | null): string {
  if (!value) throw new Error('请选择项目')
  return value
}
