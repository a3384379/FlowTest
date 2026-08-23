import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { rotationAction, type SecurityKeyVersion } from './organization-governance-rotation'

const keyVersion: SecurityKeyVersion = {
  id: '00000000-0000-4000-8000-000000009001',
  version: 2,
  key_reference: 'kms://flowtest/key/2',
  key_fingerprint: 'fingerprint-2',
  status: 'planned',
  migration_status: 'planned',
  previous_version: 1,
  created_at: '2026-08-23T00:00:00Z',
}

describe('rotationAction', () => {
  it('keeps key rotation truthful for authorized and unauthorized viewers', () => {
    expect(rotationAction(keyVersion, false)).toBeNull()

    render(rotationAction(keyVersion, true))

    expect(screen.getByText('仅元数据计划')).toBeVisible()
  })
})
