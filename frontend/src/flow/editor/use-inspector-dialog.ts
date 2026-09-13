import { useEffect, type KeyboardEvent, type RefObject } from 'react'
export function useInspectorDialog(
  active: boolean,
  root: RefObject<HTMLDivElement | null>,
  onRestore: () => void,
) {
  useEffect(() => {
    if (!active) return
    const previous = document.activeElement
    root.current?.querySelector<HTMLElement>('button,input,textarea,[tabindex="0"]')?.focus()
    return () => {
      if (previous instanceof HTMLElement && previous.isConnected) previous.focus()
    }
  }, [active, root])
  return (event: KeyboardEvent<HTMLDivElement>) => {
    if (
      !active ||
      event.nativeEvent.isComposing ||
      !event.currentTarget.contains(event.target as Node)
    )
      return
    if (event.key === 'Escape') {
      event.preventDefault()
      event.stopPropagation()
      onRestore()
      return
    }
    if (event.key !== 'Tab') return
    const controls = [
      ...event.currentTarget.querySelectorAll<HTMLElement>(
        'button:not(:disabled),input:not(:disabled),textarea:not(:disabled),[tabindex="0"]',
      ),
    ].filter((element) => !element.closest('[hidden]'))
    cycleFocus(event, controls)
  }
}
function cycleFocus(event: KeyboardEvent, controls: HTMLElement[]) {
  const first = controls.at(0)
  const last = controls.at(-1)
  if (!first || !last) return
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}
