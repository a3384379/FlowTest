import { expect, type APIRequestContext } from '@playwright/test'

/** Opt a browser acceptance project into the explicit ON policy used by security assertions. */
export async function enableProjectRedaction(
  request: APIRequestContext,
  projectId: string,
  headers: Record<string, string>,
): Promise<void> {
  const response = await request.put(`/api/v1/projects/${projectId}/redaction-policy`, {
    headers,
    data: { mode: 'on' },
  })
  expect(response.ok(), await response.text()).toBeTruthy()
}
