import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  addTeamMember,
  createTeam,
  createUser,
  listProjectMembers,
  listProjectTeamGrants,
  listTeamMembers,
  listTeams,
  listUsers,
  removeProjectMember,
  removeProjectTeamGrant,
  removeTeamMember,
  updateUser,
  upsertProjectMember,
  upsertProjectTeamGrant,
} from './access-service'
import {
  createEnvironment,
  createFolder,
  deleteFolder,
  getProjectConfiguration,
  listEnvironments,
  listFolders,
  listSecrets,
  updateEnvironment,
  updateFolder,
  updateProjectConfiguration,
  writeSecret,
} from './asset-service'
import { apiClient } from '../../lib/api'

describe('project management services', () => {
  afterEach(() => vi.restoreAllMocks())

  it('maps access-management operations to stable REST resources', async () => {
    const get = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: { items: [] } })
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: {} })
    const patch = vi.spyOn(apiClient, 'patch').mockResolvedValue({ data: {} })
    const put = vi.spyOn(apiClient, 'put').mockResolvedValue({ data: {} })
    const remove = vi.spyOn(apiClient, 'delete').mockResolvedValue({ data: {} })

    await listUsers()
    await createUser({
      email: 'member@example.com',
      display_name: 'Member',
      password: 'initial-password-123!',
      is_system_admin: false,
    })
    await updateUser('user-1', { display_name: 'Updated' })
    await listProjectMembers('project-1')
    await upsertProjectMember('project-1', 'user-1', 'editor')
    await removeProjectMember('project-1', 'user-1')
    await listTeams()
    await createTeam({ name: 'Quality', description: '' })
    await listTeamMembers('team-1')
    await addTeamMember('team-1', 'user-1')
    await removeTeamMember('team-1', 'user-1')
    await listProjectTeamGrants('project-1')
    await upsertProjectTeamGrant('project-1', 'team-1', 'viewer')
    await removeProjectTeamGrant('project-1', 'team-1')

    expect(get).toHaveBeenCalledWith('/users', expect.anything())
    expect(post).toHaveBeenCalledWith('/teams', { name: 'Quality', description: '' })
    expect(patch).toHaveBeenCalledWith('/users/user-1', { display_name: 'Updated' })
    expect(put).toHaveBeenCalledWith('/projects/project-1/team-grants/team-1', {
      team_id: 'team-1',
      role: 'viewer',
    })
    expect(remove).toHaveBeenCalledWith('/teams/team-1/members/user-1')
  })

  it('maps asset-management operations to project-scoped REST resources', async () => {
    const get = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: [] })
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: {} })
    const patch = vi.spyOn(apiClient, 'patch').mockResolvedValue({ data: {} })
    const put = vi.spyOn(apiClient, 'put').mockResolvedValue({ data: {} })
    const remove = vi.spyOn(apiClient, 'delete').mockResolvedValue({ data: {} })

    await listFolders('project-1')
    await createFolder('project-1', { name: 'Orders', parent_id: null })
    await updateFolder('project-1', 'folder-1', { name: 'Order APIs' })
    await deleteFolder('project-1', 'folder-1')
    await getProjectConfiguration('project-1')
    await updateProjectConfiguration('project-1', { variables: {}, headers: {} })
    await listEnvironments('project-1')
    await createEnvironment('project-1', {
      name: 'Test',
      base_url: 'https://api.example.com',
      variables: {},
      headers: {},
    })
    await updateEnvironment('project-1', 'environment-1', { name: 'Staging' })
    await listSecrets('project-1')
    await writeSecret('project-1', {
      name: 'API_TOKEN',
      value: 'write-only',
      environment_id: null,
    })

    expect(get).toHaveBeenCalledWith('/projects/project-1/configuration')
    expect(post).toHaveBeenCalledWith('/projects/project-1/folders', {
      name: 'Orders',
      parent_id: null,
    })
    expect(patch).toHaveBeenCalledWith('/projects/project-1/environments/environment-1', {
      name: 'Staging',
    })
    expect(put).toHaveBeenCalledWith('/projects/project-1/secrets', {
      name: 'API_TOKEN',
      value: 'write-only',
      environment_id: null,
    })
    expect(remove).toHaveBeenCalledWith('/projects/project-1/folders/folder-1')
  })
})
