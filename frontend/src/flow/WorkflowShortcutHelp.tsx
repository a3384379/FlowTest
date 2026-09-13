import { Modal, Table, Typography } from 'antd'
export default function WorkflowShortcutHelp({
  open,
  onClose,
}: {
  open: boolean
  onClose: () => void
}) {
  const rows = [
    ['Delete / Backspace', '删除选中节点或连线'],
    ['Ctrl / Cmd + C、V', '复制、粘贴单个节点'],
    ['Ctrl / Cmd + Z', '撤销'],
    ['Ctrl / Cmd + Shift + Z / Ctrl + Y', '重做'],
    ['Ctrl / Cmd + A', '全选画布对象'],
    ['Enter', '打开配置'],
    ['Shift + A', '添加节点'],
    ['Space + 拖动', '平移画布'],
    ['F', '切换专注模式'],
    ['Esc', '关闭最上层面板、取消拖动或选择'],
    ['Tab / Shift + Tab', '原生焦点导航'],
  ]
  return (
    <Modal title="画布快捷键" open={open} onCancel={onClose} footer={null}>
      <Typography.Paragraph>
        点击画布获得焦点后可用。输入框和中文输入法组合期间保持原生输入行为。
      </Typography.Paragraph>
      <Table
        size="small"
        pagination={false}
        rowKey="key"
        dataSource={rows.map(([key, action]) => ({ key, action }))}
        columns={[
          { title: '快捷键', dataIndex: 'key' },
          { title: '操作', dataIndex: 'action' },
        ]}
      />
    </Modal>
  )
}
