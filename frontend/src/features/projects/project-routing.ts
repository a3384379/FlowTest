export type ProjectSection =
  | 'dashboard'
  | 'settings'
  | 'apis'
  | 'assets'
  | 'workflows'
  | 'data'
  | 'tasks'
  | 'quality'
  | 'ai'
  | 'reports'

export function projectPath(projectId: string, section: ProjectSection): string {
  return `/projects/${projectId}/${section}`
}

export function globalPath(section: ProjectSection): string {
  return section === 'dashboard' ? '/dashboard' : `/${section}`
}

export function sectionFromPath(pathname: string): ProjectSection {
  const segment = pathname.split('/').filter(Boolean).at(-1)
  if (isProjectSection(segment)) return segment
  return 'dashboard'
}

function isProjectSection(value: string | undefined): value is ProjectSection {
  return [
    'dashboard',
    'settings',
    'apis',
    'assets',
    'workflows',
    'data',
    'tasks',
    'quality',
    'ai',
    'reports',
  ].includes(value ?? '')
}
