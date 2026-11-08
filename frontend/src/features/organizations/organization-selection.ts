const DEFAULT_SCOPE = 'default'
const ORGANIZATION_ID = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i

export function organizationSelectionKey(userId: string): string {
  return `flowtest:organization-selection:${userId}`
}

export function readOrganizationSelection(userId: string): {
  organizationId: string | null
  unavailable: boolean
} {
  try {
    const value = sessionStorage.getItem(organizationSelectionKey(userId))
    return {
      organizationId: value && ORGANIZATION_ID.test(value) ? value : null,
      unavailable: false,
    }
  } catch (error) {
    if (!(error instanceof Error)) throw error
    return { organizationId: null, unavailable: true }
  }
}

export function saveOrganizationSelection(userId: string, organizationId: string | null): boolean {
  try {
    sessionStorage.setItem(organizationSelectionKey(userId), organizationId ?? DEFAULT_SCOPE)
    return true
  } catch (error) {
    if (!(error instanceof Error)) throw error
    return false
  }
}
