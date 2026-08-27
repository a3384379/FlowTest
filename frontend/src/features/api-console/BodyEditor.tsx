import { Button, Empty, Form, Input, Segmented, Select, Space, Typography } from 'antd'
import { useRef, useState } from 'react'

import {
  recommendedContentType,
  updateAutoContentType,
  type BodyEditorFields,
  type BodyMode,
  type MultipartField,
  type RawBodyType,
} from './body-edit'
import { parseBulkKeyValues, serializeBulkKeyValues, type KeyValueField } from './bulk-edit'
import { BulkEditor, DynamicFields } from './StructuredFields'
import type { Artifact } from '../../lib/api'

type BodyFormContext = BodyEditorFields & { headers: KeyValueField[] }

export default function BodyEditor({
  artifacts,
  syncHeaders = true,
}: {
  artifacts: Artifact[]
  syncHeaders?: boolean
}) {
  const form = Form.useFormInstance<BodyFormContext>()
  const mode = Form.useWatch('body_mode', form) ?? 'none'
  const rawType = Form.useWatch('body_raw_type', form) ?? 'json'
  const autoContentType = useRef<string | null>(null)

  function syncContentType(nextMode: BodyMode, nextRawType: RawBodyType) {
    if (!syncHeaders) return
    const result = updateAutoContentType(
      form.getFieldValue('headers') ?? [],
      autoContentType.current,
      recommendedContentType(nextMode, nextRawType),
    )
    form.setFieldValue('headers', result.headers)
    autoContentType.current = result.autoValue
  }

  return (
    <Space orientation="vertical" className="full-width" size="middle">
      <Form.Item name="body_mode" label="Body 类型" className="body-mode-field">
        <Segmented<BodyMode>
          block
          aria-label="Body 类型"
          options={[
            { value: 'none', label: 'none' },
            { value: 'multipart', label: 'form-data' },
            { value: 'form', label: 'x-www-form-urlencoded' },
            { value: 'raw', label: 'raw' },
          ]}
          onChange={(value) => syncContentType(value, rawType)}
        />
      </Form.Item>
      <BodyContent
        mode={mode}
        rawType={rawType}
        artifacts={artifacts}
        onRawTypeChange={(value) => syncContentType(mode, value)}
      />
    </Space>
  )
}

function BodyContent({
  mode,
  rawType,
  artifacts,
  onRawTypeChange,
}: {
  mode: BodyMode
  rawType: RawBodyType
  artifacts: Artifact[]
  onRawTypeChange: (value: RawBodyType) => void
}) {
  if (mode === 'none') {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="该请求不发送 Body" />
  }
  if (mode === 'form') return <FormBodyFields />
  if (mode === 'multipart') return <MultipartBodyFields artifacts={artifacts} />
  return <RawBodyFields rawType={rawType} onRawTypeChange={onRawTypeChange} />
}

function RawBodyFields({
  rawType,
  onRawTypeChange,
}: {
  rawType: RawBodyType
  onRawTypeChange: (value: RawBodyType) => void
}) {
  const form = Form.useFormInstance<BodyFormContext>()
  const contentType = recommendedContentType('raw', rawType)

  function formatJson() {
    const value = form.getFieldValue('body_text')
    try {
      form.setFieldValue(
        'body_text',
        value?.trim() ? JSON.stringify(JSON.parse(value), null, 2) : '',
      )
      void form.validateFields(['body_text'])
    } catch {
      void form.validateFields(['body_text'])
    }
  }

  return (
    <>
      <Space wrap align="end" className="body-editor-toolbar">
        <Form.Item name="body_raw_type" label="raw 数据类型">
          <Select<RawBodyType>
            aria-label="raw 数据类型"
            className="body-raw-type"
            options={[
              { value: 'json', label: 'JSON' },
              { value: 'text', label: 'Text' },
              { value: 'xml', label: 'XML' },
              { value: 'html', label: 'HTML' },
            ]}
            onChange={onRawTypeChange}
          />
        </Form.Item>
        {rawType === 'json' && <Button onClick={formatJson}>格式化 JSON</Button>}
        <Typography.Text type="secondary">推荐 Content-Type：{contentType}</Typography.Text>
      </Space>
      <Form.Item
        name="body_text"
        label={rawType === 'json' ? 'JSON Body' : '原始 Body'}
        rules={rawType === 'json' ? [jsonBodyRule] : undefined}
      >
        <Input.TextArea rows={12} className="code-input" placeholder={rawPlaceholder(rawType)} />
      </Form.Item>
    </>
  )
}

function FormBodyFields() {
  const form = Form.useFormInstance<BodyFormContext>()
  const [bulkText, setBulkText] = useState<string | null>(null)
  const [bulkErrors, setBulkErrors] = useState<string[]>([])
  if (bulkText !== null) {
    return (
      <BulkEditor
        label="x-www-form-urlencoded"
        text={bulkText}
        errors={bulkErrors}
        help="每行使用“Key: Value”；# 开头为注释。当前存储结构要求 Key 唯一。"
        onChange={setBulkText}
        onCancel={() => closeBulkEditor(setBulkText, setBulkErrors)}
        onApply={() => {
          const parsed = parseBulkKeyValues(bulkText)
          setBulkErrors(parsed.errors)
          if (parsed.errors.length) return
          form.setFieldValue('body_form', parsed.values)
          setBulkText(null)
        }}
      />
    )
  }
  return (
    <>
      <Typography.Paragraph type="secondary">
        请求将使用 application/x-www-form-urlencoded 编码。
      </Typography.Paragraph>
      <Form.List name="body_form" rules={[uniqueKeyRule]}>
        {(fields, { add, remove }, { errors }) => (
          <>
            <DynamicFields
              fields={fields}
              onAdd={() => add({ name: '', value: '' })}
              onRemove={remove}
              onBulkEdit={() => {
                setBulkText(serializeBulkKeyValues(form.getFieldValue('body_form') ?? []))
                setBulkErrors([])
              }}
              render={renderTextField}
            />
            <Form.ErrorList errors={errors} />
          </>
        )}
      </Form.List>
    </>
  )
}

function MultipartBodyFields({ artifacts }: { artifacts: Artifact[] }) {
  const form = Form.useFormInstance<BodyFormContext>()
  const [bulkText, setBulkText] = useState<string | null>(null)
  const [bulkErrors, setBulkErrors] = useState<string[]>([])
  if (bulkText !== null) {
    return (
      <BulkEditor
        label="form-data 文本字段"
        text={bulkText}
        errors={bulkErrors}
        help="批量编辑仅替换 Text 类型字段，已选择的 File 字段会保留。"
        onChange={setBulkText}
        onCancel={() => closeBulkEditor(setBulkText, setBulkErrors)}
        onApply={() => {
          const parsed = parseBulkKeyValues(bulkText)
          setBulkErrors(parsed.errors)
          if (parsed.errors.length) return
          const currentFields = (form.getFieldValue('body_multipart') ?? []) as MultipartField[]
          const files = currentFields.filter((field) => field.kind === 'file')
          form.setFieldValue('body_multipart', [
            ...parsed.values.map((field) => ({ ...field, kind: 'text' as const })),
            ...files,
          ])
          setBulkText(null)
        }}
      />
    )
  }
  return (
    <>
      <Typography.Paragraph type="secondary">
        Text 字段随请求发送；File 从下方文件仓库选择，multipart boundary 将在运行时生成。
      </Typography.Paragraph>
      <Form.List name="body_multipart" rules={[uniqueMultipartTextKeyRule]}>
        {(fields, { add, remove }, { errors }) => (
          <>
            <DynamicFields
              fields={fields}
              onAdd={() => add({ name: '', kind: 'text', value: '' })}
              onRemove={remove}
              onBulkEdit={() => {
                const currentFields = (form.getFieldValue('body_multipart') ??
                  []) as MultipartField[]
                const textFields = currentFields
                  .filter((field) => field.kind === 'text')
                  .map(({ name, value }) => ({ name, value }))
                setBulkText(serializeBulkKeyValues(textFields))
                setBulkErrors([])
              }}
              bulkEditLabel="批量编辑文本字段"
              render={(field) => <MultipartRow field={field} artifacts={artifacts} />}
            />
            <Form.ErrorList errors={errors} />
          </>
        )}
      </Form.List>
    </>
  )
}

function MultipartRow({ field, artifacts }: { field: { name: number }; artifacts: Artifact[] }) {
  const form = Form.useFormInstance<BodyFormContext>()
  const kind = Form.useWatch(['body_multipart', field.name, 'kind'], form) ?? 'text'
  return (
    <>
      <Form.Item name={[field.name, 'name']} rules={[{ required: true, message: '请输入 Key' }]}>
        <Input placeholder="Key" />
      </Form.Item>
      <Form.Item name={[field.name, 'kind']}>
        <Select
          aria-label="form-data 字段类型"
          className="body-field-kind"
          options={[
            { value: 'text', label: 'Text' },
            { value: 'file', label: 'File' },
          ]}
          onChange={() => form.setFieldValue(['body_multipart', field.name, 'value'], '')}
        />
      </Form.Item>
      <Form.Item
        name={[field.name, 'value']}
        rules={kind === 'file' ? [{ required: true, message: '请选择文件' }] : undefined}
      >
        {kind === 'file' ? (
          <Select
            aria-label="form-data 文件"
            placeholder="选择文件仓库中的文件"
            options={artifacts.map((artifact) => ({
              value: artifact.id,
              label: `${artifact.filename} (${artifact.size_bytes} B)`,
            }))}
          />
        ) : (
          <Input placeholder="Value 或 {{变量}}" />
        )}
      </Form.Item>
    </>
  )
}

function renderTextField(field: { name: number }) {
  return (
    <>
      <Form.Item name={[field.name, 'name']} rules={[{ required: true, message: '请输入 Key' }]}>
        <Input placeholder="Key" />
      </Form.Item>
      <Form.Item name={[field.name, 'value']}>
        <Input placeholder="Value 或 {{变量}}" />
      </Form.Item>
    </>
  )
}

function closeBulkEditor(
  setText: (value: string | null) => void,
  setErrors: (value: string[]) => void,
) {
  setText(null)
  setErrors([])
}

function duplicateNames(values: Array<{ name?: string }>): boolean {
  const names = values.map((item) => item.name?.trim()).filter(Boolean) as string[]
  return new Set(names).size !== names.length
}

const uniqueKeyRule = {
  validator: (_: unknown, values: KeyValueField[] = []) =>
    duplicateNames(values) ? Promise.reject(new Error('Key 不能重复')) : Promise.resolve(),
}

const uniqueMultipartTextKeyRule = {
  validator: (_: unknown, values: MultipartField[] = []) =>
    duplicateNames(values.filter((field) => field.kind === 'text'))
      ? Promise.reject(new Error('Text 类型的 Key 不能重复'))
      : Promise.resolve(),
}

const jsonBodyRule = {
  validator: (_: unknown, value: string) => {
    if (!value?.trim()) return Promise.resolve()
    try {
      JSON.parse(value)
      return Promise.resolve()
    } catch {
      return Promise.reject(new Error('Body 请输入有效 JSON'))
    }
  },
}

function rawPlaceholder(rawType: RawBodyType): string {
  if (rawType === 'json') return '{\n  "name": "demo"\n}'
  if (rawType === 'xml') return '<request>demo</request>'
  if (rawType === 'html') return '<p>demo</p>'
  return '请输入原始请求内容'
}
