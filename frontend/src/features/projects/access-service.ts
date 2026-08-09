import {
  apiClient,
  type Page,
  type ProjectMember,
  type ProjectTeamGrant,
  type Team,
  type TeamMember,
  type User,
} from '../../lib/api'

export async function listUsers(): Promise<Page<User>> {
  const response = await apiClient.get<Page<User>>('/users', {
    params: { page: 1, page_size: 100 },
  })
  return response.data
}

export async function createUser(input: {
  email: string
  display_name: string
  password: string
  is_system_admin: boolean
}): Promise<User> {
  return (await apiClient.post<User>('/users', input)).data
}

export async function updateUser(
  userId: string,
  input: Partial<Pick<User, 'display_name' | 'is_active' | 'is_system_admin'>>,
): Promise<User> {
  return (await apiClient.patch<User>(`/users/${userId}`, input)).data
}

export async function listProjectMembers(projectId: string): Promise<ProjectMember[]> {
  return (await apiClient.get<ProjectMember[]>(`/projects/${projectId}/members`)).data
}

export async function upsertProjectMember(
  projectId: string,
  userId: string,
  role: ProjectMember['role'],
): Promise<ProjectMember> {
  return (
    await apiClient.put<ProjectMember>(`/projects/${projectId}/members/${userId}`, {
      user_id: userId,
      role,
    })
  ).data
}

export async function removeProjectMember(projectId: string, userId: string): Promise<void> {
  await apiClient.delete(`/projects/${projectId}/members/${userId}`)
}

export async function listTeams(): Promise<Page<Team>> {
  return (await apiClient.get<Page<Team>>('/teams', { params: { page: 1, page_size: 100 } })).data
}

export async function createTeam(input: Pick<Team, 'name' | 'description'>): Promise<Team> {
  return (await apiClient.post<Team>('/teams', input)).data
}

export async function listTeamMembers(teamId: string): Promise<TeamMember[]> {
  return (await apiClient.get<TeamMember[]>(`/teams/${teamId}/members`)).data
}

export async function addTeamMember(teamId: string, userId: string): Promise<TeamMember> {
  return (
    await apiClient.put<TeamMember>(`/teams/${teamId}/members/${userId}`, { user_id: userId })
  ).data
}

export async function removeTeamMember(teamId: string, userId: string): Promise<void> {
  await apiClient.delete(`/teams/${teamId}/members/${userId}`)
}

export async function listProjectTeamGrants(projectId: string): Promise<ProjectTeamGrant[]> {
  return (await apiClient.get<ProjectTeamGrant[]>(`/projects/${projectId}/team-grants`)).data
}

export async function upsertProjectTeamGrant(
  projectId: string,
  teamId: string,
  role: ProjectTeamGrant['role'],
): Promise<ProjectTeamGrant> {
  return (
    await apiClient.put<ProjectTeamGrant>(`/projects/${projectId}/team-grants/${teamId}`, {
      team_id: teamId,
      role,
    })
  ).data
}

export async function removeProjectTeamGrant(projectId: string, teamId: string): Promise<void> {
  await apiClient.delete(`/projects/${projectId}/team-grants/${teamId}`)
}
