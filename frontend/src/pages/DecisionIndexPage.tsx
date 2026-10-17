import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { listDecisions } from '../api/decisions'
import { DataTable } from '../components/DataTable'
import { LoadingPanel,ErrorPanel } from '../components/AsyncState'
import { StatusBadge } from '../components/StatusBadge'
export function DecisionIndexPage(){const {config}=useAuth();const q=useQuery({queryKey:['decisions'],queryFn:({signal})=>listDecisions(config,{limit:50},signal)});if(q.isLoading)return <LoadingPanel/>;if(q.error)return <ErrorPanel error={q.error}/>;return <section><h2>Decisions</h2><DataTable rows={q.data?.items||[]} rowKey={(r:any)=>r.id} columns={[{key:'id',header:'Decision',render:(r:any)=><Link to={`/decisions/${r.id}`}>{r.id}</Link>},{key:'name',header:'Decision',render:(r:any)=>r.name||r.title||r.decision||'—'},{key:'status',header:'Status',render:(r:any)=><StatusBadge value={r.status}/>}]} /></section>}
