import { useEffect, useState } from 'react'

export function useFabricPolling() {
  const [visible, setVisible] = useState(document.visibilityState !== 'hidden')
  useEffect(() => {
    const update = () => setVisible(document.visibilityState !== 'hidden')
    document.addEventListener('visibilitychange', update)
    return () => document.removeEventListener('visibilitychange', update)
  }, [])
  return {
    refetchInterval: visible ? 15_000 : (false as const),
    refetchIntervalInBackground: false,
  }
}
