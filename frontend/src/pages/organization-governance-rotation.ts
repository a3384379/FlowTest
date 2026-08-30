import { Button, Tag } from 'antd'
import { createElement, type ReactNode } from 'react'

export type SecurityKeyVersion = {
  id: string
  version: number
  key_reference: string
  key_fingerprint: string
  status: string
  migration_status: string
  previous_version: number | null
  created_at: string
}

export function rotationAction(
  item: SecurityKeyVersion,
  canRotate: boolean,
  onApply?: (id: string) => void,
  onRollback?: (id: string) => void,
): ReactNode {
  if (!canRotate) return null
  if (item.status === 'pending' && item.migration_status === 'planned') {
    return createElement(Button, { size: 'small', onClick: () => onApply?.(item.id) }, 'Apply')
  }
  if (
    item.status === 'active' &&
    item.migration_status === 'migrated' &&
    item.previous_version !== null
  ) {
    return createElement(
      Button,
      { size: 'small', danger: true, onClick: () => onRollback?.(item.id) },
      'Rollback',
    )
  }
  return createElement(
    Tag,
    { color: item.status === 'rolled_back' ? 'default' : 'success' },
    '已验证',
  )
}
