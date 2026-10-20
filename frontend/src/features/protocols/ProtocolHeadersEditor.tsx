import { Button, Collapse, Input, Space, Switch, Typography } from 'antd'
import type { ProtocolHeaderEntry } from './protocol-request-draft'

export default function ProtocolHeadersEditor({
  mode,
  rows,
  authorization,
  onAuthorization,
  onChange,
}: {
  mode: 'graphql' | 'grpc'
  rows: ProtocolHeaderEntry[]
  authorization: string
  onAuthorization: (value: string) => void
  onChange: (rows: ProtocolHeaderEntry[]) => void
}) {
  const label = mode === 'graphql' ? 'GraphQL Header' : 'gRPC Metadata'
  function update(id: string, change: Partial<ProtocolHeaderEntry>) {
    onChange(rows.map((row) => (row.id === id ? { ...row, ...change } : row)))
  }
  return (
    <Space orientation="vertical" className="full-width">
      <label>
        {mode === 'graphql' ? 'GraphQL' : 'gRPC'} Authorization
        <Input.Password
          aria-label={`${mode === 'graphql' ? 'GraphQL' : 'gRPC'} Authorization`}
          value={authorization}
          onChange={(event) => onAuthorization(event.target.value)}
          placeholder="可选，例如 Bearer …；仅用于显式调试"
          autoComplete="off"
        />
      </label>
      <Collapse
        items={[
          {
            key: 'headers',
            label: `${label}高级键值（${rows.filter((row) => row.enabled).length}项启用）`,
            children: (
              <>
                <Typography.Paragraph type="secondary">
                  {mode === 'graphql'
                    ? 'HTTP头名称不区分大小写；不能覆盖Host及连接控制头。'
                    : 'Metadata键发送时转小写，仅支持文本，不支持-bin；mTLS凭据仍由上方引用。'}
                  禁用项不发送。请求不会继承REST环境头；认证与高级配置中同名键不能重复。
                </Typography.Paragraph>
                {rows.map((row, index) => (
                  <div key={row.id} className="protocol-header-row">
                    <Switch
                      aria-label={`启用${label}${index + 1}`}
                      checked={row.enabled}
                      onChange={(enabled) => update(row.id, { enabled })}
                    />
                    <Input
                      aria-label={`${label}键${index + 1}`}
                      value={row.name}
                      onChange={(event) => update(row.id, { name: event.target.value })}
                      placeholder="键"
                    />
                    <Input
                      aria-label={`${label}值${index + 1}`}
                      value={row.value}
                      onChange={(event) => update(row.id, { value: event.target.value })}
                      placeholder="值"
                      autoComplete="off"
                    />
                    <Button
                      aria-label={`删除${label}${index + 1}`}
                      onClick={() => onChange(rows.filter((item) => item.id !== row.id))}
                    >
                      删除
                    </Button>
                  </div>
                ))}
                <Button
                  onClick={() =>
                    onChange([
                      ...rows,
                      { id: crypto.randomUUID(), enabled: true, name: '', value: '' },
                    ])
                  }
                >
                  添加{label}
                </Button>
              </>
            ),
          },
        ]}
      />
    </Space>
  )
}
