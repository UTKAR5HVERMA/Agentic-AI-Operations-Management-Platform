import { createContext, useContext } from 'react'
import type { StepId } from '@/lib/caseFlow'

export interface CaseNav {
  step: StepId
  goTo: (step: StepId) => void
  /** Open a message in the Actions step (used by "Drafted — view"). */
  openComm: (id: string) => void
  openCommId: string | null
  closeComm: () => void
}

export const CaseNavContext = createContext<CaseNav | null>(null)

/** Lets the header, banners and panels move the case view to a step or open a draft. */
export function useCaseNav(): CaseNav | null {
  return useContext(CaseNavContext)
}
