import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { App } from 'antd'
import { useLayoutEffect, useMemo, useRef } from 'react'

import { apiErrorMessage, type ApiDefinition } from '../../lib/api'
import { useRouteScopedState } from '../../lib/use-route-scoped-state'
import { useProjectCapabilities } from '../projects/use-project-capabilities'
import { useProjectContext } from '../projects/use-project-context'
import {
  applyTestDesignProposal,
  generateTestDesign,
  getTestEngineeringProposal,
  listTestEngineeringApis,
  listTestEngineeringEnvironments,
  proposeTestDesign,
  reviewTestDesignProposal,
  type TestEngineeringGeneration,
  type TestEngineeringProposal,
} from './test-engineering-service'

export function useTestEngineering(initialProposalId: string | null = null) {
  const { message } = App.useApp()
  const { projectId } = useProjectContext()
  const context = useMemo(() => ({ projectId, initialProposalId }), [projectId, initialProposalId])
  const activeContext = useRef<typeof context | null>(context)
  useLayoutEffect(() => {
    activeContext.current = context
    return () => {
      activeContext.current = null
    }
  }, [context])
  const isCurrent = () => activeContext.current === context
  const { canEdit: editPermission, permissions } = useProjectCapabilities()
  const canEdit = editPermission && permissions.isSuccess
  const queryClient = useQueryClient()
  const [generation, setGeneration] = useRouteScopedState<TestEngineeringGeneration | null>(
    projectId,
    null,
    null,
  )
  const [proposal, setProposal] = useRouteScopedState<TestEngineeringProposal | null | undefined>(
    projectId,
    initialProposalId,
    undefined,
  )
  const [selectedApi, setSelectedApi] = useRouteScopedState<ApiDefinition | null>(
    projectId,
    null,
    null,
  )
  const enabled = Boolean(projectId)
  const apis = useQuery({
    queryKey: ['test-engineering-apis', projectId],
    queryFn: () => listTestEngineeringApis(required(projectId)),
    enabled,
  })
  const environments = useQuery({
    queryKey: ['test-engineering-environments', projectId],
    queryFn: () => listTestEngineeringEnvironments(required(projectId)),
    enabled,
  })
  const linkedProposal = useQuery({
    queryKey: ['test-engineering-proposal', projectId, initialProposalId],
    queryFn: () => getTestEngineeringProposal(required(projectId), required(initialProposalId)),
    enabled: Boolean(projectId && initialProposalId),
  })
  const generate = useMutation({
    mutationKey: ['test-design-generate', projectId, initialProposalId],
    mutationFn: ({ project, apiDefinitionId }: { project: string; apiDefinitionId: string }) =>
      generateTestDesign(project, apiDefinitionId),
  })
  const propose = useMutation({
    mutationKey: ['test-design-propose', projectId, initialProposalId],
    mutationFn: (input: {
      title: string
      api_definition_id: string
      environment_id: string
      endpoint_variant?: string
      scenario_ids: string[]
    }) => proposeTestDesign(required(projectId), input),
  })
  const review = useMutation({
    mutationKey: ['test-design-review', projectId, initialProposalId],
    mutationFn: (input: { changeSetId: string; accept: boolean }) =>
      reviewTestDesignProposal(required(projectId), input.changeSetId, input.accept),
  })
  const apply = useMutation({
    mutationKey: ['test-design-apply', projectId, initialProposalId],
    mutationFn: (changeSetId: string) => applyTestDesignProposal(required(projectId), changeSetId),
  })
  const currentProposal = proposal === undefined ? linkedProposal.data : proposal
  const error = [generate.error, propose.error, review.error, apply.error].find(Boolean) ?? null

  async function generateDesign(apiDefinitionId: string): Promise<boolean> {
    propose.reset()
    review.reset()
    apply.reset()
    try {
      const generated = await generate.mutateAsync({
        project: required(projectId),
        apiDefinitionId,
      })
      if (!isCurrent()) return false
      setGeneration(generated)
      setProposal(null)
      return true
    } catch (error) {
      if (!isCurrent()) return false
      void message.error(apiErrorMessage(error))
      return false
    }
  }

  async function createProposal(input: {
    title: string
    api_definition_id: string
    environment_id: string
    endpoint_variant?: string
    scenario_ids: string[]
  }): Promise<boolean> {
    if (!canEdit || !projectId) return false
    try {
      const created = await propose.mutateAsync(input)
      if (!isCurrent()) return false
      queryClient.setQueryData(
        ['test-engineering-proposal', projectId, created.change_set_id],
        created,
      )
      setProposal(created)
      void message.success('测试设计草稿已创建，等待人工审核')
      return true
    } catch (error) {
      if (!isCurrent()) return false
      void message.error(apiErrorMessage(error))
      return false
    }
  }

  async function reviewProposal(accept: boolean): Promise<boolean> {
    if (!canEdit || !currentProposal) return false
    try {
      const reviewed = await review.mutateAsync({
        changeSetId: currentProposal.change_set_id,
        accept,
      })
      await queryClient.cancelQueries({
        queryKey: ['test-engineering-proposal', projectId, currentProposal.change_set_id],
      })
      if (!isCurrent()) return false
      queryClient.setQueryData(
        ['test-engineering-proposal', projectId, reviewed.change_set_id],
        reviewed,
      )
      setProposal(reviewed)
      void message.success(accept ? '测试设计已接受' : '测试设计已拒绝')
      return true
    } catch (error) {
      if (!isCurrent()) return false
      void message.error(apiErrorMessage(error))
      return false
    }
  }

  async function applyProposal(): Promise<boolean> {
    if (!canEdit || !currentProposal) return false
    try {
      const result = await apply.mutateAsync(currentProposal.change_set_id)
      await queryClient.cancelQueries({
        queryKey: ['test-engineering-proposal', projectId, currentProposal.change_set_id],
      })
      if (!isCurrent()) return false
      const materialized = { ...currentProposal, applied: true, materialization: result }
      queryClient.setQueryData(
        ['test-engineering-proposal', projectId, currentProposal.change_set_id],
        materialized,
      )
      setProposal(materialized)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['workflows', projectId] }),
        queryClient.invalidateQueries({ queryKey: ['test-cases', projectId] }),
        queryClient.invalidateQueries({ queryKey: ['test-case-options', projectId] }),
        queryClient.invalidateQueries({ queryKey: ['asset-directory-counts', projectId] }),
      ])
      if (!isCurrent()) return false
      void message.success(
        `已生成草稿：${result.workflow_ids.length} 个工作流 / ${result.test_case_ids.length} 个测试用例`,
      )
      return true
    } catch (error) {
      if (!isCurrent()) return false
      void message.error(apiErrorMessage(error))
      return false
    }
  }

  return {
    selectedApi,
    setSelectedApi,
    linkedProposal,
    projectId,
    canEdit,
    apis,
    environments,
    generation: visibleGeneration(initialProposalId, proposal, generation),
    proposal: currentProposal ?? null,
    permissions,
    error,
    generateDesign,
    createProposal,
    reviewProposal,
    applyProposal,
    generating: generate.isPending,
    acting: propose.isPending || review.isPending || apply.isPending,
  }
}

function visibleGeneration(
  linkedId: string | null,
  localProposal: TestEngineeringProposal | null | undefined,
  generation: TestEngineeringGeneration | null,
): TestEngineeringGeneration | null {
  return linkedId && localProposal === undefined ? null : generation
}

function required(value: string | null): string {
  if (!value) throw new Error('请选择项目')
  return value
}
