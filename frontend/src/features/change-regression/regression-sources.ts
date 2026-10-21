import type { FormInstance } from 'antd'
import type { ImpactCatalog } from '../impact/impact-service'
import type { ChangeRegressionInput } from './change-regression-service'

export type VersionPair = { baseline?: string; current?: string }
export type RegressionFormValues = Omit<ChangeRegressionInput, 'openapi_diffs' | 'schema_diffs'> & {
  openapi_pairs?: VersionPair[]
  graphql_pairs?: VersionPair[]
  grpc_pairs?: VersionPair[]
}
export type SourceField = 'openapi_pairs' | 'graphql_pairs' | 'grpc_pairs'
type SourceIssue = Parameters<FormInstance<RegressionFormValues>['setFields']>[0][number]
type SourceInput = Pick<ChangeRegressionInput, 'git_diff' | 'openapi_diffs' | 'schema_diffs'>
type SourceResult = { ok: true; input: SourceInput } | { ok: false; issues: SourceIssue[] }
export function buildRegressionSources(
  values: RegressionFormValues,
  catalog?: ImpactCatalog,
): SourceResult {
  const issues: SourceIssue[] = []
  const openapi = readPairs(
    values.openapi_pairs,
    'openapi_pairs',
    'OpenAPI',
    catalog?.targets
      .filter((item) => item.target_type === 'openapi_contract')
      .map((item) => item.id),
    issues,
  )
  const graphql = readPairs(
    values.graphql_pairs,
    'graphql_pairs',
    'GraphQL',
    catalog?.schemas.filter((item) => item.protocol === 'graphql').map((item) => item.id),
    issues,
  )
  const grpc = readPairs(
    values.grpc_pairs,
    'grpc_pairs',
    'Proto / gRPC',
    catalog?.schemas.filter((item) => item.protocol === 'grpc').map((item) => item.id),
    issues,
  )
  const gitDiff = values.git_diff?.trim() || undefined
  const schemas = [...graphql, ...grpc]
  validateSourcePresence(gitDiff, openapi.length, schemas.length, issues)
  if (issues.length) return { ok: false, issues }
  return {
    ok: true,
    input: {
      git_diff: gitDiff,
      openapi_diffs: openapi.map((pair) => ({
        baseline_run_id: pair.baseline,
        current_run_id: pair.current,
      })),
      schema_diffs: schemas.map((pair) => ({
        baseline_artifact_id: pair.baseline,
        current_artifact_id: pair.current,
      })),
    },
  }
}

function validateSourcePresence(
  gitDiff: string | undefined,
  openapiCount: number,
  schemaCount: number,
  issues: SourceIssue[],
): void {
  if (!gitDiff && !openapiCount && !schemaCount && !issues.length)
    issues.push({ name: ['git_diff'], errors: ['至少提供一种 Git Diff 或契约版本对比'] })
  if (openapiCount > 20 || schemaCount > 20)
    issues.push({
      name: ['git_diff'],
      errors: ['OpenAPI 对比最多 20 组，GraphQL 与 Proto 对比合计最多 20 组'],
    })
}

function readPairs(
  pairs: VersionPair[] | undefined,
  field: SourceField,
  label: string,
  allowed: string[] | undefined,
  issues: SourceIssue[],
): Array<{ baseline: string; current: string }> {
  const result: Array<{ baseline: string; current: string }> = []
  for (const [index, pair] of (pairs ?? []).entries()) {
    const message = pairIssue(pair, label, allowed)
    if (message) issues.push({ name: [field, index, 'current'], errors: [message] })
    else result.push({ baseline: pair.baseline!, current: pair.current! })
  }
  return result
}

function pairIssue(pair: VersionPair, label: string, allowed: string[] | undefined): string | null {
  if (!pair.baseline || !pair.current) return `请完整选择 ${label} 基线和当前版本`
  if (pair.baseline === pair.current) return `${label} 基线和当前版本必须不同`
  if (!allowed) return '版本目录未提供，请恢复读取后重试'
  if (!allowed.includes(pair.baseline) || !allowed.includes(pair.current))
    return '所选版本不属于当前项目或协议，请重新选择'
  return null
}

export function clearRegressionSourceErrors(form: FormInstance<RegressionFormValues>): void {
  const fields: SourceIssue[] = []
  for (const field of form.getFieldsError()) {
    const name = sourceErrorPath(field.name)
    if (name && field.errors.length) fields.push({ name, errors: [] })
  }
  if (fields.length) form.setFields(fields)
}

function sourceErrorPath(path: Array<string | number>): SourceIssue['name'] | null {
  const [field, index, property] = path
  if (field === 'git_diff') return ['git_diff']
  if (property !== 'current' || typeof index !== 'number') return null
  switch (field) {
    case 'openapi_pairs':
      return ['openapi_pairs', index, 'current']
    case 'graphql_pairs':
      return ['graphql_pairs', index, 'current']
    case 'grpc_pairs':
      return ['grpc_pairs', index, 'current']
    default:
      return null
  }
}
