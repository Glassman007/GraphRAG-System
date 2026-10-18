import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

const KEY='graphhacks.phase13.technical-mode'
type Ctx={technicalMode:boolean;setTechnicalMode:(v:boolean)=>void;toggle:()=>void}
const TechnicalModeContext=createContext<Ctx|null>(null)
export function TechnicalModeProvider({children}:{children:ReactNode}){
  const [technicalMode,setTechnicalMode]=useState(()=>{try{return localStorage.getItem(KEY)==='1'}catch{return false}})
  useEffect(()=>{try{localStorage.setItem(KEY,technicalMode?'1':'0')}catch{/* ignore */}},[technicalMode])
  const value=useMemo(()=>({technicalMode,setTechnicalMode,toggle:()=>setTechnicalMode(v=>!v)}),[technicalMode])
  return <TechnicalModeContext.Provider value={value}>{children}</TechnicalModeContext.Provider>
}
export function useTechnicalMode(){const v=useContext(TechnicalModeContext);if(!v)throw new Error('useTechnicalMode must be used under TechnicalModeProvider');return v}
