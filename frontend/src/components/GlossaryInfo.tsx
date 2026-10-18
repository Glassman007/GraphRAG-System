import { glossary } from '../presentation'
export function GlossaryInfo({term}:{term:string}){return <span className="glossary-info" title={glossary[term]||term} aria-label={`${term}: ${glossary[term]||term}`}>ⓘ</span>}
