import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { apiClient } from '../../lib/api'
import { authenticateTestUser } from '../../test/auth'
import { project, user } from '../../test/fixtures'
import { server } from '../../test/server'
import { useAuthStore } from '../auth/auth-store'
import {
  applyAssetPackage,
  exportAssetPackage,
  readAndPreviewAssetPackage,
} from './asset-package-service'
import { nativePackage, packageFile, packagePreview } from './asset-package.test-fixtures'

beforeEach(() => authenticateTestUser(user))
afterEach(() => {
  useAuthStore.setState({ user: null })
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

it('validates the full file with the server before exposing it to the import editor', async () => {
  const received = vi.fn()
  server.use(
    http.post(`/api/v1/projects/${project.id}/test-assets/import/preview`, async ({ request }) => {
      received(await request.json())
      return HttpResponse.json(packagePreview)
    }),
  )
  expect(await readAndPreviewAssetPackage(project.id, packageFile())).toEqual({
    package: nativePackage,
    preview: packagePreview,
  })
  expect(received).toHaveBeenCalledExactlyOnceWith({
    package: nativePackage,
    choices: [],
    bindings: {},
  })
})

it('rejects invalid JSON and oversized files without a server request', async () => {
  const writes = vi.spyOn(apiClient, 'post')
  await expect(readAndPreviewAssetPackage(project.id, packageFile('{invalid'))).rejects.toThrow(
    '合法的 JSON',
  )
  const oversized = packageFile()
  Object.defineProperty(oversized, 'size', { value: 10 * 1024 * 1024 + 1 })
  await expect(readAndPreviewAssetPackage(project.id, oversized)).rejects.toThrow('超过 10 MiB')
  expect(writes).not.toHaveBeenCalled()
})

it('does not acknowledge an import response with a different asset scope', async () => {
  server.use(
    http.post(`/api/v1/projects/${project.id}/test-assets/import/apply`, () =>
      HttpResponse.json({ assets: [] }),
    ),
  )
  await expect(
    applyAssetPackage(
      project.id,
      { package: nativePackage, choices: [], bindings: {} },
      packagePreview.fingerprint,
    ),
  ).rejects.toThrow('响应范围与确认的原生包不一致')
})

it('exports the exact selection and releases the browser download URL', async () => {
  const submitted = vi.spyOn(apiClient, 'post').mockResolvedValue({
    data: new Blob([JSON.stringify(nativePackage)], { type: 'application/json' }),
  })
  const create = vi.fn(() => 'blob:asset-package')
  const revoke = vi.fn()
  vi.stubGlobal(
    'URL',
    class extends URL {
      static createObjectURL = create
      static revokeObjectURL = revoke
    },
  )
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
  await exportAssetPackage(project.id, ['case-a'], ['suite-b'])
  expect(submitted).toHaveBeenCalledExactlyOnceWith(
    `/projects/${project.id}/test-assets/export`,
    { case_ids: ['case-a'], suite_ids: ['suite-b'] },
    { responseType: 'blob' },
  )
  expect(click).toHaveBeenCalledOnce()
  expect(create).toHaveBeenCalledOnce()
  expect(revoke).toHaveBeenCalledExactlyOnceWith('blob:asset-package')
})
