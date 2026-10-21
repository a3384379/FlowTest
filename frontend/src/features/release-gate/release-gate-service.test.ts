import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { server } from '../../test/server'
import { project } from '../../test/fixtures'
import { getDeploymentCheck } from '../contracts/contract-hub-service'
import {
  createReleaseDecision,
  createReleasePolicy,
  getReleaseDecision,
  getReleaseRunnerEvidence,
  type ReleasePolicyInput,
} from './release-gate-service'

const id = '00000000-0000-4000-8000-000000000801'
const input: ReleasePolicyInput = {
  name: '身份校验策略',
  enabled: true,
  quality_gate_id: null,
  require_quality_gate: false,
  require_contract_compatibility: false,
  require_impact_evidence: false,
  min_impact_coverage_percent: 0,
  require_release_risk: false,
  max_release_risk_score: 100,
  require_performance_evidence: false,
  require_runner_evidence: false,
}

describe('release evidence response ownership', () => {
  it.each(['id', 'project'] as const)('rejects contract %s mismatches', async (field) => {
    server.use(
      http.get(`/api/v1/projects/${project.id}/contract-hub/deployment-checks/${id}`, () =>
        HttpResponse.json({
          id: field === 'id' ? 'foreign' : id,
          project_id: field === 'project' ? 'foreign' : project.id,
        }),
      ),
    )
    await expect(getDeploymentCheck(project.id, id)).rejects.toThrow(/不一致/)
  })
  it.each(['policies', 'decisions'] as const)(
    'rejects created %s from a different project',
    async (resource) => {
      server.use(
        http.post(`/api/v1/projects/${project.id}/release-${resource}`, () =>
          HttpResponse.json({ id, project_id: 'foreign' }, { status: 201 }),
        ),
      )
      const operation =
        resource === 'policies'
          ? createReleasePolicy(project.id, input)
          : createReleaseDecision(project.id, { release_policy_id: id, candidate_ref: 'audit:v1' })
      await expect(operation).rejects.toThrow(/不一致/)
    },
  )
  it.each(['id', 'project'] as const)(
    'rejects historical decision %s mismatches',
    async (field) => {
      server.use(
        http.get(`/api/v1/projects/${project.id}/release-decisions/${id}`, () =>
          HttpResponse.json({
            id: field === 'id' ? 'foreign' : id,
            project_id: field === 'project' ? 'foreign' : project.id,
          }),
        ),
      )
      await expect(getReleaseDecision(project.id, id)).rejects.toThrow(/不一致/)
    },
  )
  it('rejects runner task ID mismatches', async () => {
    server.use(
      http.get(`/api/v1/projects/${project.id}/release-runner-evidence/${id}`, () =>
        HttpResponse.json({ id: 'foreign' }),
      ),
    )
    await expect(getReleaseRunnerEvidence(project.id, id)).rejects.toThrow(/不一致/)
  })
})
