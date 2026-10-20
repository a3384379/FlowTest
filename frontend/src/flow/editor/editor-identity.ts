export function nodeEditorScope(userId: string, projectId: string, workflowId: string): string {
  return (
    [window.location.origin, userId, projectId, workflowId].map(encodeURIComponent).join(':') + ':'
  )
}

export function regionEditorScope(scope: string, regionId: string): string {
  return `${scope}region:${encodeURIComponent(regionId)}:`
}
