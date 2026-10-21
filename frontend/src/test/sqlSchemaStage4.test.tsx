import { expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { sqlSchemaToGraph } from '../graph/adapters'
import { SqlSchemaPanel } from '../pages/SqlSchemaPanel'

vi.mock('../auth/AuthContext', () => ({useAuth: () => ({config: {baseUrl: '', token: 'reader', tenantId: 'schema-test'}, hasPermission: () => false})}))
vi.mock('../components/GraphView', () => ({GraphView: ({graph, onNode}: any) => <div>
  {graph.nodes.map((node: any) => <button key={node.id} onClick={() => onNode(node)}>{node.label}</button>)}
  <span>{graph.edges.length} graph connections</span>
</div>}))

const tables = ['payment', 'rental', 'inventory', 'film'].map(name => ({id: name, name: `public.${name}`}))
const foreign_keys = [
  ['payment', 'rental', 'payment_rental_id_fkey'],
  ['rental', 'inventory', 'rental_inventory_id_fkey'],
  ['inventory', 'film', 'inventory_film_id_fkey'],
].map(([source_id, target_id, constraint_name]) => ({source_id, target_id,
  properties: {edge_id: constraint_name, constraint_name}}))

it('adapts persisted table and FK responses into the existing graph view', () => {
  const graph = sqlSchemaToGraph({tables, foreign_keys})
  expect(graph.nodes.map(node => node.label)).toEqual(tables.map(table => table.name))
  expect(graph.edges.map(edge => [edge.source, edge.target, edge.type])).toEqual([
    ['payment', 'rental', 'FOREIGN_KEY_TO'],
    ['rental', 'inventory', 'FOREIGN_KEY_TO'],
    ['inventory', 'film', 'FOREIGN_KEY_TO'],
  ])
})

it('loads API graph, inspects a table and follows its recorded FK', async () => {
  const source = {source_repository: 'sample/repo', source_file_path: 'schema.sql', source_commit_sha: 'a'.repeat(40),
    source_file_hash: 'b'.repeat(64), source_uri: `https://github.com/sample/repo/blob/${'a'.repeat(40)}/schema.sql`}
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
    const url = String(input)
    const data = url.endsWith('/sql-schema/payment') ? {
      table: tables[0], columns: [{id: 'col', column_name: 'rental_id', data_type: 'integer'}],
      constraints: [{id: 'fk', constraint_name: 'payment_rental_id_fkey', constraint_type: 'FOREIGN_KEY',
        columns: ['rental_id'], referenced_table: 'public.rental', referenced_columns: ['rental_id'], ddl_line: 10,
        source_uri: source.source_uri}],
      foreign_keys: [{source: tables[0], target: tables[1], properties: {edge_id: 'fk', constraint_name: 'payment_rental_id_fkey', source_columns: ['rental_id'], target_columns: ['rental_id']}}],
      source: {file: source, repository: {name: 'sample/repo'}},
    } : url.endsWith('/sql-schema/rental') ? {
      table: tables[1], columns: [], constraints: [], foreign_keys: [], source: {file: source},
    } : {tables, foreign_keys, truncated: false}
    return new Response(JSON.stringify(data), {status: 200, headers: {'Content-Type': 'application/json'}})
  })
  const client = new QueryClient({defaultOptions: {queries: {retry: false}}})
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/company-brain?tab=sql-schema']}><SqlSchemaPanel /></MemoryRouter></QueryClientProvider>)
  expect(await screen.findByText('3 graph connections')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', {name: 'public.payment'}))
  expect(await screen.findByText('rental_id')).toBeInTheDocument()
  expect(screen.getAllByText('payment_rental_id_fkey', {exact: false})).toHaveLength(2)
  expect(screen.getByText('sample/repo')).toBeInTheDocument()
  expect(screen.getByRole('link', {name: 'Source line 10'})).toHaveAttribute('href', expect.stringContaining('#L10'))
  fireEvent.click(screen.getByRole('button', {name: 'To public.rental'}))
  await waitFor(() => expect(fetchMock.mock.calls.some(call => String(call[0]).endsWith('/sql-schema/rental'))).toBe(true))
  fetchMock.mockRestore()
})
