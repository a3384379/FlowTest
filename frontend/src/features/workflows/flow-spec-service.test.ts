import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import { project, workflow } from '../../test/fixtures'
import { server } from '../../test/server'
import {
  applyFlowSpec,
  diffFlowSpecs,
  exportFlowSpec,
  importFlowSpec,
  reviewFlowSpec,
  validateFlowSpec,
} from './flow-spec-service'

const spec = {
  schema_version: 'flowtest-flow-spec-v1' as const,
  fingerprint_version: 'flowtest-flow-spec-fingerprint-v2' as const,
  project_id: project.id,
  name: workflow.name,
  description: workflow.description,
  source_evidence: [],
  services: [],
  operations: [],
  nodes: [],
  edges: [],
  variables: {},
  settings: workflow.draft_definition.settings,
  bindings: [],
  parameters: [],
  assertions: [],
  cleanup: [],
  security_policy: { secret_refs_only: true, max_requests: 20, allow_private_network: false },
  confidence: { overall: 1, unresolved: [] },
}

describe('flow spec service', () => {
  it('keeps export, validation, review, and apply endpoints typed', async () => {
    const exported = {
      fingerprint: 'f'.repeat(64),
      spec,
      validation: { valid: true },
      compatibility: {},
    }
    const changeSet = {
      id: 'change-set-1',
      project_id: project.id,
      title: workflow.name,
      status: 'draft',
      source_type: 'flow_spec',
      source_ref: null,
      source_fingerprint: 'f'.repeat(64),
      target_workflow_id: workflow.id,
      target_revision: 1,
      target_snapshot_sha256: 'a'.repeat(64),
      review_status: 'pending',
      reviewed_by_id: null,
      reviewed_at: null,
      applied_at: null,
      created_by_id: 'user-1',
      created_at: '2026-08-22T00:00:00Z',
      updated_at: '2026-08-22T00:00:00Z',
      spec,
      validation: { valid: true, issues: [], warnings: [], requires_review: false },
      compatibility: {
        compatible: true,
        source_schema_version: 'flowtest-flow-spec-v1',
        target_schema_version: 'flowtest-flow-spec-v1',
        blockers: [],
        warnings: [],
        requires_review: true,
      },
      diff: [],
    }
    server.use(
      http.get(`/api/v1/projects/${project.id}/flow-specs/workflows/${workflow.id}/export`, () =>
        HttpResponse.json({
          ...exported,
          workflow_id: workflow.id,
          version: null,
          draft_revision: 1,
        }),
      ),
      http.post(`/api/v1/projects/${project.id}/flow-specs/validate`, () =>
        HttpResponse.json({ ...exported }),
      ),
      http.post(`/api/v1/projects/${project.id}/flow-specs/diff`, () =>
        HttpResponse.json({
          before_fingerprint: null,
          after_fingerprint: exported.fingerprint,
          changes: [],
        }),
      ),
      http.post(`/api/v1/projects/${project.id}/flow-specs/imports`, () =>
        HttpResponse.json(changeSet, { status: 201 }),
      ),
      http.post(
        `/api/v1/projects/${project.id}/flow-specs/change-sets/${changeSet.id}/review`,
        () => HttpResponse.json({ ...changeSet, status: 'accepted', review_status: 'accepted' }),
      ),
      http.post(`/api/v1/projects/${project.id}/flow-specs/change-sets/${changeSet.id}/apply`, () =>
        HttpResponse.json({
          change_set_id: changeSet.id,
          workflow_id: workflow.id,
          draft_revision: 2,
          fingerprint: changeSet.source_fingerprint,
          applied_at: '2026-08-22T00:00:00Z',
        }),
      ),
    )

    expect((await exportFlowSpec(project.id, workflow.id)).workflow_id).toBe(workflow.id)
    expect((await validateFlowSpec(project.id, spec)).fingerprint).toBe(exported.fingerprint)
    expect((await diffFlowSpecs(project.id, null, spec)).changes).toEqual([])
    expect((await importFlowSpec(project.id, spec, workflow.id)).id).toBe(changeSet.id)
    expect((await reviewFlowSpec(project.id, changeSet.id, true, '确认')).status).toBe('accepted')
    expect((await applyFlowSpec(project.id, changeSet.id)).draft_revision).toBe(2)
  })
})
