import type { WorkflowDefinition, WorkflowNode } from '../../lib/api'

export function locatedNodes(definition: WorkflowDefinition, regionId?: string) {
  return regionId
    ? (definition.regions?.find((region) => region.id === regionId)?.nodes ?? [])
    : definition.nodes
}

export function replaceLocatedNode(
  definition: WorkflowDefinition,
  node: WorkflowNode,
  regionId?: string,
): WorkflowDefinition {
  const nodes = locatedNodes(definition, regionId).map((item) =>
    item.id === node.id ? node : item,
  )
  return regionId
    ? {
        ...definition,
        regions: definition.regions?.map((region) =>
          region.id === regionId ? { ...region, nodes } : region,
        ),
      }
    : { ...definition, nodes }
}
