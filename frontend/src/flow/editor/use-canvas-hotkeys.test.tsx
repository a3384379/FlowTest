import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { useCanvasHotkeys } from './use-canvas-hotkeys'
function Harness({ blocked = false, run }: { blocked?: boolean; run: () => void }) {
  const onKeyDown = useCanvasHotkeys({ delete: run, undo: run, redo: run, add: run }, blocked)
  return (
    <div tabIndex={0} aria-label="画布" onKeyDown={onKeyDown}>
      <input aria-label="输入" />
      <button>表单按钮</button>
      <div role="textbox" contentEditable suppressContentEditableWarning>
        富文本
      </div>
    </div>
  )
}
describe('canvas keyboard boundaries', () => {
  it('executes only supported focused canvas commands', () => {
    const run = vi.fn()
    render(<Harness run={run} />)
    const canvas = screen.getByLabelText('画布')
    for (const key of ['Delete', 'Backspace']) fireEvent.keyDown(canvas, { key })
    fireEvent.keyDown(canvas, { key: 'z', metaKey: true })
    fireEvent.keyDown(canvas, { key: 'z', ctrlKey: true, shiftKey: true })
    fireEvent.keyDown(canvas, { key: 'A', shiftKey: true })
    expect(run).toHaveBeenCalledTimes(5)
    expect(fireEvent.keyDown(canvas, { key: 'Tab' })).toBe(true)
    fireEvent.keyDown(canvas, { key: 'Delete', isComposing: true })
    fireEvent.keyDown(canvas, { key: 'Delete', repeat: true })
    fireEvent.keyDown(canvas, { key: 'Delete', altKey: true })
    expect(run).toHaveBeenCalledTimes(5)
  })
  it('does not intercept input, rich text, buttons, or a modal-blocked canvas', () => {
    const run = vi.fn()
    const view = render(<Harness run={run} />)
    for (const target of [
      screen.getByLabelText('输入'),
      screen.getByRole('button'),
      screen.getByText('富文本'),
    ]) {
      expect(fireEvent.keyDown(target, { key: 'Backspace' })).toBe(true)
      fireEvent.keyDown(target, { key: 'z', ctrlKey: true })
    }
    expect(run).not.toHaveBeenCalled()
    view.rerender(<Harness run={run} blocked />)
    fireEvent.keyDown(screen.getByLabelText('画布'), { key: 'Delete' })
    expect(run).not.toHaveBeenCalled()
  })
})

it('blocks a canvas behind a portal dialog and restores commands once it closes', () => {
  const run = vi.fn()
  const view = render(
    <>
      <Harness run={run} />
      <div role="dialog" aria-modal="true">
        弹层
      </div>
    </>,
  )
  fireEvent.keyDown(screen.getByLabelText('画布'), { key: 'Delete' })
  expect(run).not.toHaveBeenCalled()
  view.rerender(
    <>
      <Harness run={run} />
      <div className="ant-drawer">
        <div role="dialog" aria-modal="true">
          已关闭抽屉
        </div>
      </div>
    </>,
  )
  fireEvent.keyDown(screen.getByLabelText('画布'), { key: 'Delete' })
  expect(run).toHaveBeenCalledTimes(1)
})
