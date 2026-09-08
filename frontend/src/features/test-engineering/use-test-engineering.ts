import { useMutation, useQuery } from '@tanstack/react-query'
import { App } from 'antd'

import { apiErrorMessage } from '../../lib/api'
import { useRouteScopedState } from '../../lib/use-route-scoped-state'
import { useProjectContext } from '../projects/use-project-context'
import {
  applyTestDesignProposal,
  generateTestDesign,
  getTestEngineeringProposal,
  listTestEngineeringApis,
  listTestEngineeringEnvironments,
  proposeTestDesign,
  reviewTestDesignProposal,
  type TestEngineeringProposal,
} from './test-engineering-service'

export function useTestEngineering(initialProposalId: string | null = null) {
  const { message } = App.useApp()
  const { projectId } = useProjectContext()
  const [proposal, setProposal] = useRouteScopedState<TestEngineeringProposal | null>(
    projectId,
    initialProposalId,
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
    mutationFn: (apiDefinitionId: string) =>
      generateTestDesign(required(projectId), apiDefinitionId),
  })
  const propose = useMutation({
    mutationFn: (input: {
      title: string
      api_definition_id: string
      environment_id: string
      endpoint_variant?: string
      scenario_ids: string[]
    }) => proposeTestDesign(required(projectId), input),
  })
  const review = useMutation({
    mutationFn: (input: { changeSetId: string; accept: boolean }) =>
      reviewTestDesignProposal(required(projectId), input.changeSetId, input.accept),
  })
  const apply = useMutation({
    mutationFn: (changeSetId: string) => applyTestDesignProposal(required(projectId), changeSetId),
  })

  async function generateDesign(apiDefinitionId: string): Promise<boolean> {
    try {
      await generate.mutateAsync(apiDefinitionId)
      setProposal(null)
      return true
    } catch (error) {
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
    try {
      setProposal(await propose.mutateAsync(input))
      void message.success('Test Design Draft 已创建，等待人工审核')
      return true
    } catch (error) {
      void message.error(apiErrorMessage(error))
      return false
    }
  }

  async function reviewProposal(accept: boolean): Promise<boolean> {
    const currentProposal = proposal ?? linkedProposal.data
    if (!currentProposal) return false
    try {
      setProposal(await review.mutateAsync({ changeSetId: currentProposal.change_set_id, accept }))
      void message.success(accept ? 'Proposal 已接受' : 'Proposal 已拒绝')
      return true
    } catch (error) {
      void message.error(apiErrorMessage(error))
      return false
    }
  }

  async function applyProposal(): Promise<boolean> {
    const currentProposal = proposal ?? linkedProposal.data
    if (!currentProposal) return false
    try {
      const result = await apply.mutateAsync(currentProposal.change_set_id)
      setProposal({ ...currentProposal, applied: true })
      void message.success(
        `已进入现有执行体系：${result.workflow_ids.length} 个 Workflow / ${result.test_case_ids.length} 个 TestCase`,
      )
      return true
    } catch (error) {
      void message.error(apiErrorMessage(error))
      return false
    }
  }

  return {
    projectId,
    apis,
    environments,
    generation: generate.data ?? null,
    proposal: proposal ?? linkedProposal.data ?? null,
    generateDesign,
    createProposal,
    reviewProposal,
    applyProposal,
    generating: generate.isPending,
    acting: propose.isPending || review.isPending || apply.isPending,
  }
}

function required(value: string | null): string {
  if (!value) throw new Error('请选择项目')
  return value
}
