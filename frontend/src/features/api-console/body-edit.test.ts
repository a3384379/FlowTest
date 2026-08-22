import { describe, expect, it } from 'vitest'

import {
  recommendedContentType,
  toBodyFields,
  toBodyInput,
  updateAutoContentType,
} from './body-edit'

describe('API workbench Body conversion', () => {
  it('maps JSON and raw bodies to Postman-style raw editors', () => {
    expect(toBodyFields({ body_kind: 'json', body: { active: true }, headers: {} })).toMatchObject({
      body_mode: 'raw',
      body_raw_type: 'json',
      body_text: '{\n  "active": true\n}',
    })
    expect(
      toBodyFields({
        body_kind: 'raw',
        body: '<user />',
        headers: { 'Content-Type': 'application/xml' },
      }),
    ).toMatchObject({ body_mode: 'raw', body_raw_type: 'xml', body_text: '<user />' })
  })

  it('round-trips form and multipart fields', () => {
    const form = toBodyFields({ body_kind: 'form', body: { username: 'demo' }, headers: {} })
    expect(toBodyInput(form)).toEqual({ body_kind: 'form', body: { username: 'demo' } })

    const multipart = toBodyFields({
      body_kind: 'multipart',
      body: {
        fields: { description: 'avatar' },
        files: [{ field: 'file', artifact_id: 'artifact-1' }],
      },
      headers: {},
    })
    expect(multipart.body_multipart).toEqual([
      { name: 'description', kind: 'text', value: 'avatar' },
      { name: 'file', kind: 'file', value: 'artifact-1' },
    ])
    expect(toBodyInput(multipart)).toEqual({
      body_kind: 'multipart',
      body: {
        fields: { description: 'avatar' },
        files: [{ field: 'file', artifact_id: 'artifact-1' }],
      },
    })
  })

  it('tracks automatic Content-Type without overwriting explicit headers', () => {
    expect(recommendedContentType('raw', 'json')).toBe('application/json')
    const added = updateAutoContentType([], null, 'application/json')
    expect(added).toEqual({
      headers: [{ name: 'Content-Type', value: 'application/json' }],
      autoValue: 'application/json',
    })
    expect(updateAutoContentType(added.headers, added.autoValue, 'application/xml')).toEqual({
      headers: [{ name: 'Content-Type', value: 'application/xml' }],
      autoValue: 'application/xml',
    })
    expect(
      updateAutoContentType(
        [{ name: 'Content-Type', value: 'application/custom' }],
        null,
        'application/json',
      ),
    ).toEqual({
      headers: [{ name: 'Content-Type', value: 'application/custom' }],
      autoValue: null,
    })
  })
})
