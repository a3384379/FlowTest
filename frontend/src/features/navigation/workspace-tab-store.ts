import { sectionLabels } from './navigation-config'
import { projectPath, type ProjectSection } from '../projects/project-routing'

export type WorkspaceTab = {
  key: string
  section: ProjectSection
  objectId: string | null
  href: string
  label: string
}

export type WorkspaceTabRead = { tabs: WorkspaceTab[]; error: string | null }

export function routeWorkspaceTab(projectId: string, href: string): WorkspaceTab | null {
  if (!href.startsWith('/') || href.startsWith('//') || href.includes('\\') || href.length > 8192)
    return null
  const route = new URL(href, 'https://workspace.invalid')
  const parts = route.pathname.split('/')
  const section = parts[3]
  if (
    parts.length !== 4 ||
    parts[1] !== 'projects' ||
    parts[2] !== projectId ||
    !Object.hasOwn(sectionLabels, section)
  )
    return null
  const typedSection = section as ProjectSection
  const objectId = objectIdentity(typedSection, route.searchParams)
  return {
    key: objectId ? `${section}:${objectId}` : section,
    section: typedSection,
    objectId,
    href: `${route.pathname}${route.search}${route.hash}`,
    label: defaultLabel(typedSection, objectId),
  }
}

function objectIdentity(section: ProjectSection, params: URLSearchParams): string | null {
  if (section === 'reports') return params.get('execution') || null
  return section === 'apis' || section === 'workflows' ? params.get('focus') || null : null
}

function defaultLabel(section: ProjectSection, objectId: string | null): string {
  if (!objectId) return sectionLabels[section]
  const names: Partial<Record<ProjectSection, string>> = {
    apis: '接口',
    workflows: '流程',
    reports: '报告',
  }
  return `${names[section]} · ${objectId.slice(0, 12)}`
}

export function workspaceTabStorageKey(userId: string, projectId: string): string {
  return `flowtest:workspace-tabs:v2:${encodeURIComponent(userId)}:${encodeURIComponent(projectId)}`
}

export function readWorkspaceTabs(userId: string, projectId: string): WorkspaceTabRead {
  try {
    const raw = localStorage.getItem(workspaceTabStorageKey(userId, projectId))
    if (raw === null) return readLegacyTabs(userId, projectId)
    if (raw.length > 1_000_000) return { tabs: [], error: '工作区标签数据过大，已使用当前会话导航' }
    const value: unknown = JSON.parse(raw)
    return parseWorkspaceTabs(value, projectId)
  } catch {
    return { tabs: [], error: '工作区标签无法恢复，当前会话仍可导航' }
  }
}

function parseWorkspaceTabs(value: unknown, projectId: string): WorkspaceTabRead {
  if (!isWorkspacePayload(value))
    return { tabs: [], error: '工作区标签格式不兼容，当前会话仍可导航' }
  const tabs: WorkspaceTab[] = []
  for (const item of value.tabs.slice(0, 512)) {
    const tab = parseTab(item, projectId)
    if (tab && !tabs.some((existing) => existing.key === tab.key)) tabs.push(tab)
  }
  return { tabs, error: tabs.length === value.tabs.length ? null : '部分无效工作区标签未恢复' }
}

function isWorkspacePayload(value: unknown): value is { schemaVersion: 2; tabs: unknown[] } {
  return Boolean(
    value &&
    typeof value === 'object' &&
    'schemaVersion' in value &&
    value.schemaVersion === 2 &&
    'tabs' in value &&
    Array.isArray(value.tabs),
  )
}

function parseTab(value: unknown, projectId: string): WorkspaceTab | null {
  if (!value || typeof value !== 'object' || !('href' in value) || typeof value.href !== 'string')
    return null
  const tab = routeWorkspaceTab(projectId, value.href)
  if (!tab) return null
  if ('label' in value && typeof value.label === 'string' && value.label.length <= 512)
    tab.label = value.label
  return tab
}

function readLegacyTabs(userId: string, projectId: string): WorkspaceTabRead {
  const value: unknown = JSON.parse(
    localStorage.getItem(`flowtest:workspace-tabs:v1:${userId}:${projectId}`) ?? '[]',
  )
  if (!Array.isArray(value))
    return { tabs: [], error: '旧版工作区标签格式不兼容，当前会话仍可导航' }
  const tabs = value.flatMap((section: unknown) => {
    if (typeof section !== 'string' || !Object.hasOwn(sectionLabels, section)) return []
    const tab = routeWorkspaceTab(projectId, projectPath(projectId, section as ProjectSection))
    return tab ? [tab] : []
  })
  return { tabs, error: null }
}

export function writeWorkspaceTabs(
  userId: string,
  projectId: string,
  tabs: WorkspaceTab[],
): string | null {
  try {
    localStorage.setItem(
      workspaceTabStorageKey(userId, projectId),
      JSON.stringify({ schemaVersion: 2, tabs }),
    )
    return null
  } catch {
    return '工作区标签仅保留在本次会话，刷新后可能无法恢复；资源草稿请在编辑页保存。'
  }
}
