import { Button, Form } from 'antd'
import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import BodyEditor from './BodyEditor'

describe('BodyEditor edge cases', () => {
  it('supports XML and HTML placeholders and rejects invalid bulk form input', async () => {
    const browser = userEvent.setup()
    render(<BodyEditorHarness />)

    await browser.click(screen.getByText('raw', { exact: true }))
    await chooseRawType(browser, 'XML')
    expect(screen.getByPlaceholderText('<request>demo</request>')).toBeVisible()
    await chooseRawType(browser, 'HTML')
    expect(screen.getByPlaceholderText('<p>demo</p>')).toBeVisible()
    await chooseRawType(browser, 'JSON')
    await browser.click(screen.getByRole('button', { name: '格式化 JSON' }))

    await browser.click(screen.getByText('x-www-form-urlencoded', { exact: true }))
    await browser.click(screen.getByRole('button', { name: '批量编辑' }))
    fireEvent.change(screen.getByLabelText('批量编辑 x-www-form-urlencoded'), {
      target: { value: '缺少分隔符' },
    })
    await browser.click(screen.getByRole('button', { name: '应用并返回表格' }))
    expect(screen.getByText(/第 1 行/)).toBeVisible()
    await browser.click(screen.getByRole('button', { name: /取\s*消/ }))
    expect(screen.queryByLabelText('批量编辑 x-www-form-urlencoded')).not.toBeInTheDocument()
  })

  it('validates duplicate form and multipart text keys', async () => {
    const browser = userEvent.setup()
    render(<BodyEditorHarness />)

    await browser.click(screen.getByText('x-www-form-urlencoded', { exact: true }))
    await addDuplicateKeys(browser)
    await browser.click(screen.getByRole('button', { name: /提\s*交/ }))
    expect(await screen.findByText('Key 不能重复')).toBeInTheDocument()

    await browser.click(screen.getByText('form-data', { exact: true }))
    await addDuplicateKeys(browser)
    await browser.click(screen.getByRole('button', { name: /提\s*交/ }))
    expect(await screen.findByText('Text 类型的 Key 不能重复')).toBeInTheDocument()
  })
})

function BodyEditorHarness() {
  return (
    <Form
      initialValues={{
        body_mode: 'none',
        body_raw_type: 'json',
        body_text: '',
      }}
      onFinish={vi.fn()}
    >
      <BodyEditor artifacts={[]} />
      <Button htmlType="submit">提交</Button>
    </Form>
  )
}

async function chooseRawType(browser: ReturnType<typeof userEvent.setup>, name: string) {
  await browser.click(screen.getByLabelText('raw 数据类型'))
  await browser.click(screen.getByText(name, { exact: true }))
}

async function addDuplicateKeys(browser: ReturnType<typeof userEvent.setup>) {
  const editor = screen.getByText(/请求将使用|Text 字段随请求发送/).parentElement
  if (!editor) throw new Error('Body editor was not rendered')
  await browser.click(within(editor).getByRole('button', { name: /添加一行/ }))
  await browser.click(within(editor).getByRole('button', { name: /添加一行/ }))
  const keys = within(editor).getAllByPlaceholderText('Key')
  await browser.type(keys[0], 'duplicate')
  await browser.type(keys[1], 'duplicate')
}
