import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Space, Spin } from 'antd'
import { Fragment, useLayoutEffect, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'

import { useAuthStore } from '../auth/auth-store'
import { useDraftSession } from '../drafts/draft-session'
import { apiErrorWithTrace, SessionBoundaryError, setOrganizationId } from '../../lib/api'
import { OrganizationScopeContext } from './organization-scope-context'
import { listOrganizations, type Organization } from './organization-service'
import { readOrganizationSelection, saveOrganizationSelection } from './organization-selection'

export default function OrganizationScopeProvider({ children }: { children: ReactNode }) {
  const user = useAuthStore((state) => state.user)!
  const epoch = useAuthStore((state) => state.epoch)
  const organizationId = useAuthStore((state) => state.organizationId)
  const queryClient = useQueryClient()
  const drafts = useDraftSession()
  const navigate = useNavigate()
  const [storageUnavailable, setStorageUnavailable] = useState(false)
  useLayoutEffect(
    () =>
      useAuthStore.subscribe((state, previous) => {
        if (state.organizationId !== previous.organizationId && state.epoch === previous.epoch) {
          if (state.user) {
            setStorageUnavailable(!saveOrganizationSelection(state.user.id, state.organizationId))
          }
          queryClient.clear()
        }
      }),
    [queryClient],
  )
  const catalog = useQuery({
    queryKey: ['organization-scope', user.id, epoch, organizationId],
    queryFn: () => authorizedOrganizations(user.id, epoch, user.is_system_admin),
    retry: false,
  })
  const selectOrganization = (id: string | null) => {
    const current = useAuthStore.getState()
    if (current.user?.id !== user.id || current.epoch !== epoch || drafts.unsafe.size > 0) return
    if (id && !catalog.data?.organizations.some((item) => item.id === id)) return
    setStorageUnavailable(!saveOrganizationSelection(user.id, id))
    setOrganizationId(id)
    navigate('/dashboard')
  }
  const activeAllowed =
    !organizationId || catalog.data?.organizations.some((item) => item.id === organizationId)
  if (catalog.isPending)
    return (
      <main className="centered-page">
        <Spin tip="正在核对组织访问权限" />
      </main>
    )
  if (catalog.isError || !activeAllowed) {
    return (
      <OrganizationScopeFailure
        error={catalog.error}
        retry={() => void catalog.refetch()}
        reset={() => {
          selectOrganization(null)
          void catalog.refetch()
        }}
      />
    )
  }
  return (
    <OrganizationScopeContext.Provider
      value={{ organizations: catalog.data.organizations, organizationId, selectOrganization }}
    >
      {(storageUnavailable || catalog.data.storageUnavailable) && (
        <Alert type="warning" title="浏览器无法保存组织选择，刷新后需要重新选择。" />
      )}
      {catalog.data.selectionRevoked && (
        <Alert type="warning" title="已保存的组织已不可访问，当前使用账户默认域。" />
      )}
      <Fragment key={`${user.id}:${epoch}:${organizationId ?? 'default'}`}>{children}</Fragment>
    </OrganizationScopeContext.Provider>
  )
}

async function authorizedOrganizations(
  userId: string,
  epoch: number,
  systemAdmin: boolean,
): Promise<{
  organizations: Organization[]
  selectionRevoked: boolean
  storageUnavailable: boolean
}> {
  const initialScope = useAuthStore.getState().organizationId
  const organizations = (await listOrganizations()).filter(
    (item) => item.enabled && (item.role !== null || systemAdmin),
  )
  const current = useAuthStore.getState()
  if (
    current.user?.id !== userId ||
    current.epoch !== epoch ||
    current.organizationId !== initialScope
  )
    throw new SessionBoundaryError()
  const saved = readOrganizationSelection(userId)
  const permitted = organizations.some((item) => item.id === saved.organizationId)
  if (!initialScope && saved.organizationId && permitted) setOrganizationId(saved.organizationId)
  return {
    organizations,
    storageUnavailable: saved.unavailable,
    selectionRevoked: Boolean(!initialScope && saved.organizationId && !permitted),
  }
}

function OrganizationScopeFailure({
  error,
  retry,
  reset,
}: {
  error: Error | null
  retry: () => void
  reset: () => void
}) {
  return (
    <main className="centered-page">
      <Space orientation="vertical">
        <Alert
          type="error"
          title="无法确认组织访问权限"
          description={error ? apiErrorWithTrace(error) : '当前组织已不可访问，请返回账户默认域。'}
        />
        <Button onClick={retry}>重新核对</Button>
        <Button onClick={reset}>返回账户默认域</Button>
      </Space>
    </main>
  )
}
