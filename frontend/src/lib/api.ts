import axios from 'axios'

export const apiClient = axios.create({
  baseURL: '/api/v1',
  timeout: 30_000,
  withCredentials: true,
})

let accessToken: string | null = null

export function setAccessToken(token: string | null) {
  accessToken = token
}

apiClient.interceptors.request.use((config) => {
  if (accessToken) {
    config.headers.Authorization = `Bearer ${accessToken}`
  }
  return config
})

export type Page<T> = {
  items: T[]
  total: number
  page: number
  page_size: number
}

export type User = {
  id: string
  email: string
  display_name: string
  is_active: boolean
  is_system_admin: boolean
  requires_password_change: boolean
}

export type Project = {
  id: string
  name: string
  description: string
  role: 'owner' | 'editor' | 'viewer' | null
}

export type Environment = {
  id: string
  project_id: string
  name: string
  base_url: string
  variables: Record<string, string>
  headers: Record<string, string>
}

export type ApiDefinition = {
  id: string
  project_id: string
  folder_id: string | null
  name: string
  description: string
  current_version: number
}

export type AssertionResult = {
  id: string
  kind: string
  target: string | null
  expected: unknown
  actual: unknown
  passed: boolean
  message: string
}

export type Execution = {
  id: string
  status: 'running' | 'passed' | 'failed' | 'error'
  request_method: string
  request_url: string
  request_headers: Record<string, string>
  request_body: unknown
  response_status: number | null
  response_headers: Record<string, string>
  response_body: unknown
  elapsed_ms: number | null
  error_code: string | null
  error_message: string | null
  started_at: string
}

export type ExecutionDetail = {
  execution: Execution
  assertions: AssertionResult[]
}

export function apiErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const message = error.response?.data?.error?.message
    return typeof message === 'string' ? message : error.message
  }
  return error instanceof Error ? error.message : '请求失败，请稍后重试'
}
