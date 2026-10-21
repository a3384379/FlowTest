export type ChangeField = { path: string; before: unknown; after: unknown }
export function proposedDraft(
  before: Record<string, unknown>,
  patch: Record<string, unknown>,
  targetType: 'test_case' | 'workflow',
): Record<string, unknown> {
  const after = {
    ...before,
    ...Object.fromEntries(
      Object.entries(patch).filter(([, value]) => value !== null && value !== undefined),
    ),
  }
  if (isObject(before.definition) && isObject(patch.definition)) {
    after.definition =
      targetType === 'test_case'
        ? retainOmitted(before.definition, patch.definition, [
            'runtime_variables',
            'runtime_headers',
          ])
        : workflowDefinition(before.definition, patch.definition)
  }
  return after
}

function retainOmitted(
  before: Record<string, unknown>,
  patch: Record<string, unknown>,
  fields: readonly string[],
): Record<string, unknown> {
  const after = { ...patch }
  for (const field of fields) {
    if (!Object.hasOwn(patch, field) && Object.hasOwn(before, field)) after[field] = before[field]
  }
  return after
}

function workflowDefinition(
  before: Record<string, unknown>,
  patch: Record<string, unknown>,
): Record<string, unknown> {
  const after = retainOmitted(before, patch, ['variables'])
  if (!Array.isArray(before.nodes) || !Array.isArray(patch.nodes)) return after
  const previous = new Map<string, Record<string, unknown>>()
  for (const node of before.nodes) {
    if (isObject(node) && typeof node.id === 'string') previous.set(node.id, node)
  }
  after.nodes = patch.nodes.map((node: unknown) => mergedNode(previous, node))
  return after
}

function mergedNode(before: Map<string, Record<string, unknown>>, node: unknown): unknown {
  if (!isObject(node) || typeof node.id !== 'string') return node
  const previous = before.get(node.id)
  return previous ? retainOmitted(previous, node, ['config', 'configuration']) : node
}
export function changeFields(before: unknown, after: unknown, path = '$'): ChangeField[] {
  if (JSON.stringify(before) === JSON.stringify(after)) return []
  if (!isObject(before) || !isObject(after)) return [{ path, before, after }]
  return [...new Set([...Object.keys(before), ...Object.keys(after)])].flatMap((key) =>
    changeFields(before[key], after[key], `${path}.${key}`),
  )
}
function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value))
}
