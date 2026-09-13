import type { KeyboardEvent } from 'react'

export type CanvasCommands = {
  delete?: () => void
  copy?: () => void
  paste?: () => void
  undo?: () => void
  redo?: () => void
  configure?: () => void
  add?: () => void
  focus?: () => void
  escape?: () => void
  help?: () => void
}
export function isInputTarget(target: EventTarget | null): boolean {
  return (
    target instanceof Element &&
    Boolean(
      target.closest(
        'input,textarea,select,[contenteditable]:not([contenteditable="false"]),[role="textbox"],[role="combobox"],.monaco-editor,.cm-editor,button,[role="dialog"]',
      ),
    )
  )
}
function commandName(event: KeyboardEvent): keyof CanvasCommands | undefined {
  const key = event.key.toLowerCase()
  if (event.ctrlKey || event.metaKey) {
    if (key === 'z') return event.shiftKey ? 'redo' : 'undo'
    return ({ c: 'copy', v: 'paste', y: 'redo' } as const)[key as 'c' | 'v' | 'y']
  }
  if (key === 'tab' && !event.shiftKey) return 'add'
  return (
    {
      delete: 'delete',
      backspace: 'delete',
      enter: 'configure',
      f: 'focus',
      escape: 'escape',
      '?': 'help',
    } as const
  )[key as 'delete' | 'backspace' | 'enter' | 'f' | 'escape' | '?']
}
export function useCanvasHotkeys(commands: CanvasCommands, blocked: boolean) {
  return (event: KeyboardEvent<HTMLDivElement>) => {
    if (ignoreShortcut(event, blocked)) return
    if (!event.currentTarget.contains(event.target as Node) || isInputTarget(event.target)) return
    const name = commandName(event)
    if (name === 'add' && document.activeElement !== event.currentTarget) return
    const command = name && commands[name]
    if (!command || event.repeat) return
    event.preventDefault()
    event.stopPropagation()
    command()
  }
}

function hasBlockingDialog(): boolean {
  return [...document.querySelectorAll<HTMLElement>('[role="dialog"][aria-modal="true"]')].some(
    (dialog) => {
      const drawer = dialog.closest('.ant-drawer')
      if (drawer) return drawer.classList.contains('ant-drawer-open')
      const wrapper = dialog.closest<HTMLElement>('.ant-modal-wrap') ?? dialog
      return (
        !wrapper.closest('[hidden]') &&
        getComputedStyle(wrapper).display !== 'none' &&
        getComputedStyle(wrapper).visibility !== 'hidden'
      )
    },
  )
}

function ignoreShortcut(event: KeyboardEvent, blocked: boolean): boolean {
  return (
    blocked ||
    hasBlockingDialog() ||
    event.defaultPrevented ||
    event.nativeEvent.isComposing ||
    event.altKey
  )
}
