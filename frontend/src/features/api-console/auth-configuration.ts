import type { ApiVersion } from '../../lib/api'
import type { KeyValueField } from './bulk-edit'

type AuthField = { name: string; label: string; fallback?: string; required?: boolean }
export const authConfigurationFields: Readonly<
  Record<ApiVersion['auth_kind'], readonly AuthField[]>
> = {
  none: [],
  bearer: [{ name: 'token', label: 'Bearer Token' }],
  basic: [
    { name: 'username', label: 'Basic 用户名' },
    { name: 'password', label: 'Basic 密码', required: false },
  ],
  api_key: [
    { name: 'name', label: 'API Key 名称', fallback: 'X-API-Key' },
    { name: 'value', label: 'API Key 值' },
    { name: 'in', label: 'API Key 位置', fallback: 'header' },
  ],
}

export function authFieldValue(values: KeyValueField[], field: AuthField): string {
  return values.find((item) => item.name === field.name)?.value ?? field.fallback ?? ''
}

export function validateAuthConfiguration(
  kind: ApiVersion['auth_kind'],
  values: KeyValueField[],
): void {
  if (new Set(values.map((item) => item.name)).size !== values.length)
    throw new Error('认证配置键名不能重复')
  const missing = authConfigurationFields[kind].find(
    (field) => field.required !== false && !authFieldValue(values, field).length,
  )
  if (missing) throw new Error(`请填写${missing.label}`)
  if (
    kind === 'api_key' &&
    !['header', 'query', 'cookie'].includes(
      authFieldValue(values, authConfigurationFields.api_key[2]),
    )
  )
    throw new Error('请选择 API Key 位置')
}
