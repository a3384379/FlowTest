import { projectPath } from '../projects/project-routing'

export function contractServiceLocation(params: URLSearchParams, legacyImpact = false) {
  const focus = params.get('focus')
  const legacy = focus?.startsWith('contract_service:')
    ? focus.slice('contract_service:'.length)
    : null
  const value =
    params.get('contractServiceId') ?? legacy ?? (legacyImpact ? params.get('service_id') : null)
  if (value === null) return { id: null, error: null }
  return /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value)
    ? { id: value.toLowerCase(), error: null }
    : { id: null, error: 'URL 中的目录服务 ID 无效' }
}

export function contractServicePath(
  projectId: string,
  section: 'services' | 'contracts' | 'impact',
  id: string,
) {
  return `${projectPath(projectId, section)}?${new URLSearchParams({ contractServiceId: id })}`
}
