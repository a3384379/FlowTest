import { Select, Tooltip } from 'antd'
import { useSyncExternalStore } from 'react'

import { useDraftSession } from '../drafts/draft-session'
import { useOrganizationScope } from './organization-scope-context'

const DEFAULT_SCOPE = 'account-default'

export default function OrganizationSelector() {
  const { organizations, organizationId, selectOrganization } = useOrganizationScope()
  const drafts = useDraftSession()
  useSyncExternalStore(drafts.subscribe, drafts.snapshot)
  const unsafe = drafts.unsafe.size > 0
  return (
    <Tooltip
      title={
        unsafe ? '请先保存当前草稿再切换组织' : '组织决定可访问的项目范围；默认域由账户配置决定'
      }
    >
      <Select
        aria-label="全局组织"
        className="global-organization-select"
        disabled={unsafe}
        value={organizationId ?? DEFAULT_SCOPE}
        onChange={(value: string) => selectOrganization(value === DEFAULT_SCOPE ? null : value)}
        options={[
          { value: DEFAULT_SCOPE, label: '个人 / 默认域' },
          ...organizations.map((item) => ({ value: item.id, label: item.name })),
        ]}
      />
    </Tooltip>
  )
}
