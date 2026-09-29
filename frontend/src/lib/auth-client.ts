import axios from 'axios'

export const authClient = axios.create({
  baseURL: '/api/v1',
  timeout: 30_000,
  withCredentials: true,
  headers: { 'X-Requested-With': 'FlowTest' },
})

export class SessionBoundaryError extends Error {}
