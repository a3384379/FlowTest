import { Button } from 'antd'
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
  onApply: (id: string) => void,
  onRollback: (id: string) => void,
  pending: boolean,
): ReactNode {
  if (!canRotate) return null
  if (item.status === 'pending') {
    return createElement(
      Button,
      { size: 'small', onClick: () => onApply(item.id), loading: pending },
      'Apply',
    )
  }
  if (item.status === 'active' && item.version > 1) {
    return createElement(
      Button,
      { size: 'small', danger: true, onClick: () => onRollback(item.id), loading: pending },
      'Rollback',
    )
  }
  return null
}
