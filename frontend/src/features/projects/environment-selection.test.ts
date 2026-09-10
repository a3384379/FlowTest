import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

import { useAuthStore } from '../auth/auth-store'
import { user, environment } from '../../test/fixtures'
import { useEnvironmentSelection } from './environment-selection'

afterEach(() => {
  localStorage.clear()
  useAuthStore.setState({ user: null })
})

it('shares selection across modules and restores it after remount', () => {
  useAuthStore.setState({ user })
  const environments = [environment, { ...environment, id: 'B' }]
  const first = renderHook(() => useEnvironmentSelection('shared', environments))
  const second = renderHook(() => useEnvironmentSelection('shared', environments))
  expect(first.result.current.environmentId).toBeNull()
  act(() => first.result.current.selectEnvironment('B'))
  expect(second.result.current.environmentId).toBe('B')
  first.unmount()
  second.unmount()
  const restored = renderHook(() => useEnvironmentSelection('shared', environments))
  expect(restored.result.current.environmentId).toBe('B')
})

it('does not silently replace a deleted explicit selection with the only remaining environment', () => {
  useAuthStore.setState({ user })
  const hook = renderHook(({ items }) => useEnvironmentSelection('deleted', items), {
    initialProps: { items: [environment, { ...environment, id: 'B' }] },
  })
  act(() => hook.result.current.selectEnvironment('B'))
  hook.rerender({ items: [environment] })
  expect(hook.result.current.environmentId).toBeNull()
  expect(hook.result.current.selectionInvalid).toBe(true)
  hook.unmount()
  const restored = renderHook(() => useEnvironmentSelection('deleted', [environment]))
  expect(restored.result.current.environmentId).toBeNull()
})

it('isolates projects and users and permits initial selection only for one environment', () => {
  useAuthStore.setState({ user })
  const items = [environment, { ...environment, id: 'B' }]
  const first = renderHook(() => useEnvironmentSelection('one', items))
  act(() => first.result.current.selectEnvironment('B'))
  const other = renderHook(() => useEnvironmentSelection('two', items))
  expect(other.result.current.environmentId).toBeNull()
  act(() => useAuthStore.setState({ user: { ...user, id: 'other-user' } }))
  expect(first.result.current.environmentId).toBeNull()
  const unique = renderHook(() => useEnvironmentSelection('unique', [environment]))
  expect(unique.result.current.environmentId).toBe(environment.id)
})

it('does not select a target when persistence fails', async () => {
  useAuthStore.setState({ user })
  const set = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
    throw new DOMException('full', 'QuotaExceededError')
  })
  const hook = renderHook(() => useEnvironmentSelection('storage-error', [environment]))
  await waitFor(() => expect(hook.result.current.environmentPlaceholder).toContain('无法保存'))
  expect(hook.result.current.environmentId).toBeNull()
  set.mockRestore()
})
