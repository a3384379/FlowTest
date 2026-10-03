import { Alert, Button, Space, Switch, Typography } from 'antd'
import { useMemo, useState, type ReactNode } from 'react'

export default function ResponseCodeReader({ value, title }: { value: unknown; title: string }) {
  const [pretty, setPretty] = useState(true)
  const [wrap, setWrap] = useState(false)
  const [copyStatus, setCopyStatus] = useState<string | null>(null)
  const text = useMemo(() => formatCode(value, pretty), [value, pretty])
  const lines = text.slice(0, 64_000).split('\n').slice(0, 300)
  const preview = lines.join('\n')
  const truncated = preview.length < text.length

  async function copy() {
    try {
      await navigator.clipboard.writeText(text)
      setCopyStatus('已复制完整内容')
    } catch {
      setCopyStatus('复制失败，请下载内容或手动选择复制')
    }
  }

  return (
    <section className="response-reader" aria-label={title}>
      <Space wrap className="response-reader-toolbar">
        <Typography.Text strong>{title}</Typography.Text>
        <Switch
          checked={pretty}
          onChange={setPretty}
          checkedChildren="格式化"
          unCheckedChildren="原文"
          aria-label={`${title}格式化`}
        />
        <Switch
          checked={wrap}
          onChange={setWrap}
          checkedChildren="自动换行"
          unCheckedChildren="横向滚动"
          aria-label={`${title}自动换行`}
        />
        <Button size="small" onClick={() => void copy()}>
          复制完整内容
        </Button>
        <Button size="small" onClick={() => downloadText(text, title)}>
          下载完整内容
        </Button>
        {copyStatus && <Typography.Text role="status">{copyStatus}</Typography.Text>}
      </Space>
      {truncated && (
        <Alert type="info" title="仅预览前 300 行或 64,000 字符，复制和下载包含完整已捕获内容。" />
      )}
      <div className={`response-reader-code${wrap ? ' is-wrapped' : ''}`} tabIndex={0}>
        <pre className="response-line-numbers" aria-hidden="true">
          {lines.map((_, index) => index + 1).join('\n')}
        </pre>
        <pre className="response-reader-text">
          {typeof value === 'object' ? highlightJson(preview) : preview}
        </pre>
      </div>
    </section>
  )
}

function highlightJson(text: string): ReactNode[] {
  const result: ReactNode[] = []
  const tokens = /"(?:\\.|[^"\\])*"|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|\b(?:true|false|null)\b/g
  let offset = 0
  for (const match of text.matchAll(tokens)) {
    result.push(text.slice(offset, match.index))
    const end = match.index + match[0].length
    result.push(
      <span key={match.index} className={`response-token-${tokenKind(match[0], text.slice(end))}`}>
        {match[0]}
      </span>,
    )
    offset = end
  }
  result.push(text.slice(offset))
  return result
}

function tokenKind(token: string, suffix: string): string {
  if (token.startsWith('"')) return suffix.trimStart().startsWith(':') ? 'key' : 'string'
  if (token === 'true' || token === 'false' || token === 'null') return 'keyword'
  return 'number'
}

function formatCode(value: unknown, pretty: boolean): string {
  if (value === undefined) return '未提供'
  if (typeof value === 'string') return value
  return JSON.stringify(value, null, pretty ? 2 : undefined) ?? '未提供'
}

function downloadText(text: string, title: string) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' }))
  try {
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `${title}.txt`
    anchor.click()
  } finally {
    URL.revokeObjectURL(url)
  }
}
