import { Link,useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '../../auth/AuthContext'
import { listRuns } from '../../api/sources'
import { ErrorPanel,LoadingPanel,EmptyState } from '../../components/AsyncState'
import { presentRun } from '../../presentation'
export function IngestionRunsPage(){const {config}=useAuth();const [sp]=useSearchParams();const sourceId=sp.get('source_id')||undefined;const q=useQuery({queryKey:['ingestion-runs',sourceId],queryFn:({signal})=>listRuns(config,sourceId,signal)});if(q.isLoading)return <LoadingPanel/>;if(q.error)return <ErrorPanel error={q.error}/>;const items=q.data?.items||[];return <section><h2>Ingestion runs</h2><p>Synchronization history across organizational sources.</p>{!items.length?<EmptyState title="No ingestion runs yet"/>:items.map((r:any)=>{const p=presentRun(r);return <Link className="panel row-link" key={r.id} to={`/sources/runs/${r.id}`}><strong>{p.title}</strong><span>{p.subtitle}</span><span>{p.outcome}</span></Link>})}</section>}
