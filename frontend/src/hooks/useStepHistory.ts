import { useState, useEffect, useCallback } from 'react'
import { StepHistory } from '../types'
import { fetchStepHistory } from '../lib/api'

export function useStepHistory(projectName: string | null) {
  const [history, setHistory] = useState<StepHistory>({})

  const reload = useCallback(async () => {
    if (!projectName) return
    try {
      const data = await fetchStepHistory(projectName)
      setHistory(data)
    } catch (err) {
      console.error("Failed to load step history", err)
    }
  }, [projectName])

  useEffect(() => {
    reload()
  }, [reload])

  return { history, reloadHistory: reload }
}
