import { Alert, Button, Popconfirm } from 'antd'
import { apiErrorWithTrace } from '../../lib/api'
import type { SelfTestInstallation } from './self-test-contract'
import { useSelfTestIdentity } from './self-test-query-keys'
import { resumeSelfTestInstallation } from './self-test-service'
import { useSelfTestCommand } from './use-self-test-command'

export default function SelfTestInstallationRecovery({
  installation,
  projectId,
  allowed,
}: {
  installation: SelfTestInstallation
  projectId: string
  allowed: boolean
}) {
  const identity = useSelfTestIdentity(projectId)
  const command = useSelfTestCommand({
    identity,
    selectionKey: `${installation.id}:${installation.revision}`,
    allowed,
    send: (_input: undefined, key: string) =>
      resumeSelfTestInstallation(projectId, installation, key),
  })
  if (['ready', 'archived'].includes(installation.status)) return null
  return (
    <>
      <Alert
        type="warning"
        title="恢复沿用原安装与宿主 journal"
        description="已完成资源保持原映射；结果未知的创建必须由原宿主核对，不会另建安装或盲目重放。有效租约结束前不能恢复。"
      />
      <Popconfirm
        title="继续原安装初始化？"
        description="需由保留原状态目录与 nonce 的已登记宿主继续处理。"
        onConfirm={() => command.execute(undefined)}
      >
        <Button disabled={!allowed || command.pending} loading={command.pending}>
          继续初始化
        </Button>
      </Popconfirm>
      {Boolean(command.error) && <Alert type="error" title={apiErrorWithTrace(command.error)} />}
    </>
  )
}
