import { describe, expect, it } from 'vitest'

import { globalPath, projectPath } from '../projects/project-routing'
import {
  groupForSection,
  navigationGroups,
  sectionLabels,
  visibleSections,
} from './navigation-config'

describe('navigation configuration', () => {
  it('maps the 26 original leaves exactly once into dashboard and six groups', () => {
    const sections = ['dashboard', ...navigationGroups.flatMap((group) => group.sections)]
    expect(navigationGroups).toHaveLength(6)
    expect(new Set(sections).size).toBe(26)
    expect([...sections].sort()).toEqual(Object.keys(sectionLabels).sort())
    expect(navigationGroups.every((group) => group.key.startsWith('nav:'))).toBe(true)
    expect(groupForSection('dashboard')).toBeUndefined()
    expect(groupForSection('workflows')?.label).toBe('测试设计')
  })

  it('keeps organization available to members while filtering only the two admin leaves', () => {
    expect(visibleSections(true)).toHaveLength(26)
    expect(visibleSections(false)).toHaveLength(24)
    expect(visibleSections(false)).toContain('organization')
    expect(visibleSections(false)).not.toContain('fabric')
    expect(visibleSections(false)).not.toContain('platform')
  })

  it('keeps existing global redirects and project URLs for every section', () => {
    for (const section of visibleSections(true)) {
      expect(globalPath(section)).toBe(section === 'fabric' ? '/execution-fabric' : `/${section}`)
      expect(projectPath('project-1', section)).toBe(`/projects/project-1/${section}`)
    }
  })
})
