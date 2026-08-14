export type ProjectSection =
  | 'dashboard'
  | 'settings'
  | 'apis'
  | 'protocols'
  | 'assets'
  | 'workflows'
  | 'data'
  | 'tasks'
  | 'performance'
  | 'environments'
  | 'contracts'
  | 'impact'
  | 'quality'
  | 'ai'
  | 'ai-changes'
  | 'reports'
  | 'platform'
  | 'fabric'

export function projectPath(projectId: string, section: ProjectSection): string {
  return `/projects/${projectId}/${section}`
}

export function globalPath(section: ProjectSection): string {
  if (section === 'fabric') return '/execution-fabric'
  return section === 'dashboard' ? '/dashboard' : `/${section}`
}

export function sectionFromPath(pathname: string): ProjectSection {
  const segment = pathname.split('/').filter(Boolean).at(-1)
  if (segment === 'execution-fabric') return 'fabric'
  if (isProjectSection(segment)) return segment
  return 'dashboard'
}

function isProjectSection(value: string | undefined): value is ProjectSection {
  return [
    'dashboard',
    'settings',
    'apis',
    'protocols',
    'assets',
    'workflows',
    'data',
    'tasks',
    'performance',
    'environments',
    'contracts',
    'impact',
    'quality',
    'ai',
    'ai-changes',
    'reports',
    'platform',
    'fabric',
  ].includes(value ?? '')
}
