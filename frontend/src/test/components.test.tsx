import { describe,expect,it } from 'vitest'
import { render,screen } from '@testing-library/react'
import { StatusBadge } from '../components/StatusBadge'
import { EmptyState,ErrorPanel,LoadingPanel } from '../components/AsyncState'
import { DataTable } from '../components/DataTable'
import { FilterBar } from '../components/FilterBar'
describe('shared functional UI',()=>{
 it('renders loading state',()=>{render(<LoadingPanel label="Loading graph"/>);expect(screen.getByRole('status')).toHaveTextContent('Loading graph')})
 it('renders empty state',()=>{render(<EmptyState title="No claims"/>);expect(screen.getByText('No claims')).toBeInTheDocument()})
 it('renders error state',()=>{render(<ErrorPanel error={new Error('boom')}/>);expect(screen.getByRole('alert')).toHaveTextContent('boom')})
 it('renders status badge',()=>{render(<StatusBadge value="READY"/>);expect(screen.getByText('READY')).toBeInTheDocument()})
 it('renders filter controls with an accessible label',()=>{render(<FilterBar label="Graph filters"><input aria-label="Node type"/></FilterBar>);expect(screen.getByLabelText('Graph filters')).toBeInTheDocument();expect(screen.getByLabelText('Node type')).toBeInTheDocument()})
 it('renders table headers and rows',()=>{render(<DataTable rows={[{id:'1'}]} rowKey={r=>r.id} columns={[{key:'id',header:'ID',render:r=>r.id}]}/>);expect(screen.getByRole('columnheader',{name:'ID'})).toBeInTheDocument();expect(screen.getByText('1')).toBeInTheDocument()})
})

describe('functional requirements',()=>{
 it('does not require decorative rendering to expose status',()=>{render(<StatusBadge value="ALREADY_COMPLETED"/>);expect(screen.getByText('ALREADY_COMPLETED')).toBeVisible()})
})
