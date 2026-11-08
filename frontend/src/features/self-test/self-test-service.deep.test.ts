import { http, HttpResponse } from 'msw'
import { expect, it } from 'vitest'
import { apiClient, SessionBoundaryError } from '../../lib/api'
import { selfTestIds } from './self-test-test-fixtures'
import { server } from '../../test/server'
import { authenticateTestUser } from '../../test/auth'
import { project, user } from '../../test/fixtures'
import { selfTestInstallation } from './self-test-test-fixtures'
import { resumeSelfTestInstallation } from './self-test-service'

it('sends the original installation revision and explicit recovery intent key', async () => {
  authenticateTestUser(user)
  let receivedKey: string | null = null
  let body: unknown
  server.use(
    http.post(
      `/api/v1/projects/${project.id}/self-tests/installations/${selfTestInstallation.id}/resume`,
      async ({ request }) => {
        receivedKey = request.headers.get('Idempotency-Key')
        body = await request.json()
        return HttpResponse.json(selfTestInstallation)
      },
    ),
  )
  await resumeSelfTestInstallation(project.id, selfTestInstallation, 'resume-intent')
  expect(receivedKey).toBe('resume-intent')
  expect(body).toEqual({
    expected_revision: selfTestInstallation.revision,
    environment_fingerprint: selfTestInstallation.environment_fingerprint,
    confirmed: true,
  })
})

it('keeps the initiating identity through asynchronous Axios preparation', async () => {
  authenticateTestUser(user)
  let release!: () => void
  let entered!: () => void
  const barrier = new Promise<void>((resolve) => {
    release = resolve
  })
  const waiting = new Promise<void>((resolve) => {
    entered = resolve
  })
  let writes = 0
  server.use(
    http.post(
      `/api/v1/projects/${project.id}/self-tests/installations/${selfTestInstallation.id}/resume`,
      () => {
        writes += 1
        return HttpResponse.json(selfTestInstallation)
      },
    ),
  )
  const interceptor = apiClient.interceptors.request.use(async (config) => {
    entered()
    await barrier
    return config
  })
  try {
    const result = resumeSelfTestInstallation(
      project.id,
      selfTestInstallation,
      'identity-bound-resume',
    ).catch((failure: unknown) => failure)
    await waiting
    authenticateTestUser({ ...user, id: selfTestIds.task })
    release()
    expect(await result).toBeInstanceOf(SessionBoundaryError)
    expect(writes).toBe(0)
  } finally {
    release()
    apiClient.interceptors.request.eject(interceptor)
  }
})
