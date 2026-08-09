import {
  apiClient,
  type Environment,
  type Folder,
  type ProjectConfiguration,
  type SecretMetadata,
} from '../../lib/api'

export async function listFolders(projectId: string): Promise<Folder[]> {
  return (await apiClient.get<Folder[]>(`/projects/${projectId}/folders`)).data
}

export async function createFolder(
  projectId: string,
  input: { name: string; parent_id: string | null },
): Promise<Folder> {
  return (await apiClient.post<Folder>(`/projects/${projectId}/folders`, input)).data
}

export async function updateFolder(
  projectId: string,
  folderId: string,
  input: { name?: string; parent_id?: string | null },
): Promise<Folder> {
  return (await apiClient.patch<Folder>(`/projects/${projectId}/folders/${folderId}`, input)).data
}

export async function deleteFolder(projectId: string, folderId: string): Promise<void> {
  await apiClient.delete(`/projects/${projectId}/folders/${folderId}`)
}

export async function getProjectConfiguration(projectId: string): Promise<ProjectConfiguration> {
  return (await apiClient.get<ProjectConfiguration>(`/projects/${projectId}/configuration`)).data
}

export async function updateProjectConfiguration(
  projectId: string,
  configuration: Omit<ProjectConfiguration, 'project_id'>,
): Promise<ProjectConfiguration> {
  return (
    await apiClient.put<ProjectConfiguration>(`/projects/${projectId}/configuration`, configuration)
  ).data
}

export async function listEnvironments(projectId: string): Promise<Environment[]> {
  return (await apiClient.get<Environment[]>(`/projects/${projectId}/environments`)).data
}

export async function createEnvironment(
  projectId: string,
  input: Omit<Environment, 'id' | 'project_id'>,
): Promise<Environment> {
  return (await apiClient.post<Environment>(`/projects/${projectId}/environments`, input)).data
}

export async function updateEnvironment(
  projectId: string,
  environmentId: string,
  input: Partial<Omit<Environment, 'id' | 'project_id'>>,
): Promise<Environment> {
  return (
    await apiClient.patch<Environment>(
      `/projects/${projectId}/environments/${environmentId}`,
      input,
    )
  ).data
}

export async function listSecrets(projectId: string): Promise<SecretMetadata[]> {
  return (await apiClient.get<SecretMetadata[]>(`/projects/${projectId}/secrets`)).data
}

export async function writeSecret(
  projectId: string,
  input: { name: string; value: string; environment_id: string | null },
): Promise<SecretMetadata> {
  return (await apiClient.put<SecretMetadata>(`/projects/${projectId}/secrets`, input)).data
}
