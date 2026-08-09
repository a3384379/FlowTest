import { describe, expect, it } from 'vitest'

import { globalPath, projectPath, sectionFromPath } from './project-routing'

describe('project routing', () => {
  it('creates stable global and project-scoped paths', () => {
    expect(globalPath('dashboard')).toBe('/dashboard')
    expect(globalPath('apis')).toBe('/apis')
    expect(projectPath('project-1', 'workflows')).toBe('/projects/project-1/workflows')
  })

  it('reads supported sections and falls back safely', () => {
    expect(sectionFromPath('/projects/project-1/reports')).toBe('reports')
    expect(sectionFromPath('/unexpected')).toBe('dashboard')
  })
})
