import type { ReactNode } from 'react'
import { useTechnicalMode } from '../presentation/TechnicalModeContext'
export function TechnicalDetails({title='Technical details',children,force=false}:{title?:string;children:ReactNode;force?:boolean}){const {technicalMode}=useTechnicalMode();return <details className="technical-details" open={force||technicalMode}><summary>{title}</summary><div className="technical-details-body">{children}</div></details>}
