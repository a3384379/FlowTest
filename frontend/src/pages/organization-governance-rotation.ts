import { Tag } from 'antd'
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

export function rotationAction(_item: SecurityKeyVersion, canRotate: boolean): ReactNode {
  if (!canRotate) return null
  return createElement(Tag, { color: 'warning' }, '仅元数据计划')
}
