import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { rotationAction, type SecurityKeyVersion } from './organization-governance-rotation'

const keyVersion: SecurityKeyVersion = {
  id: '00000000-0000-4000-8000-000000009001',
  version: 2,
  key_reference: 'kms://flowtest/key/2',
  key_fingerprint: 'fingerprint-2',
  status: 'pending',
  migration_status: 'planned',
  previous_version: 1,
  created_at: '2026-08-23T00:00:00Z',
}

describe('rotationAction', () => {
  it('keeps rotation actions permissioned and state-specific', async () => {
    expect(rotationAction(keyVersion, false)).toBeNull()

    let applied = ''
    const { rerender } = render(
      rotationAction(keyVersion, true, (id) => {
        applied = id
      }),
    )
    await userEvent.click(screen.getByRole('button', { name: 'Apply' }))
    expect(applied).toBe(keyVersion.id)

    let rolledBack = ''
    rerender(
      rotationAction(
        { ...keyVersion, status: 'active', migration_status: 'migrated' },
        true,
        undefined,
        (id) => {
          rolledBack = id
        },
      ),
    )
    await userEvent.click(screen.getByRole('button', { name: 'Rollback' }))
    expect(rolledBack).toBe(keyVersion.id)
  })
})
