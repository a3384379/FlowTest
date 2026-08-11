import { describe, expect, it } from 'vitest'

import { globalPath, projectPath, sectionFromPath } from './project-routing'

describe('project routing', () => {
  it('creates stable global and project-scoped paths', () => {
    expect(globalPath('dashboard')).toBe('/dashboard')
    expect(globalPath('apis')).toBe('/apis')
    expect(projectPath('project-1', 'workflows')).toBe('/projects/project-1/workflows')
    expect(projectPath('project-1', 'assets')).toBe('/projects/project-1/assets')
    expect(projectPath('project-1', 'quality')).toBe('/projects/project-1/quality')
    expect(projectPath('project-1', 'ai')).toBe('/projects/project-1/ai')
  })

  it('reads supported sections and falls back safely', () => {
    expect(sectionFromPath('/projects/project-1/reports')).toBe('reports')
    expect(sectionFromPath('/projects/project-1/quality')).toBe('quality')
    expect(sectionFromPath('/projects/project-1/ai')).toBe('ai')
    expect(sectionFromPath('/unexpected')).toBe('dashboard')
  })
})
