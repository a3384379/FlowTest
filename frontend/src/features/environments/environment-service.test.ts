import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { server } from '../../test/server'
import {
  getEnvironmentInstance,
  getEnvironmentTemplateVersion,
  getInstanceTemplateVersion,
  type EnvironmentInstance,
} from './environment-service'

describe('environment read identity', () => {
  it('rejects responses for another exact version or project instance', async () => {
    server.use(
      http.get('/api/v1/environment-templates/versions/old-id', () =>
        HttpResponse.json({ id: 'new-id' }),
      ),
      http.get('/api/v1/projects/owned/environment-instances/instance', () =>
        HttpResponse.json({ id: 'instance', project_id: 'foreign' }),
      ),
    )
    await expect(getEnvironmentTemplateVersion('old-id')).rejects.toThrow('与所选ID不符')
    await expect(getEnvironmentInstance('owned', 'instance')).rejects.toThrow('与当前项目或ID不符')
  })
  it.each([
    { id: 'other', version: 1, template_key: 'platform.web' },
    { id: 'old-id', version: 2, template_key: 'platform.web' },
    { id: 'old-id', version: 1, template_key: 'foreign.key' },
  ])('rejects a substituted binding %o', async (response) => {
    server.use(
      http.get('/api/v1/projects/owned/environment-instances/instance/template-version', () =>
        HttpResponse.json(response),
      ),
    )
    const instance = {
      id: 'instance',
      project_id: 'owned',
      template_version_id: 'old-id',
      template_key: 'platform.web',
      template_version: 1,
    } as EnvironmentInstance
    await expect(getInstanceTemplateVersion('owned', instance)).rejects.toThrow(
      '与实例固定绑定不符',
    )
  })
})
