import { afterEach, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AddSourcePage } from '../pages/sources/AddSourcePage'
import { SourceDetailPage } from '../pages/sources/SourceDetailPage'
import * as sources from '../api/sources'
import { TechnicalModeProvider } from '../presentation/TechnicalModeContext'

vi.mock('../auth/AuthContext', () => ({useAuth: () => ({config: {baseUrl: '', token: 'local', tenantId: 'isolated'}})}))
afterEach(() => vi.restoreAllMocks())

it('registers a public repository, pinned commit and selected SQL file without a credential', async () => {
  vi.spyOn(sources, 'listConnectors').mockResolvedValue({items: [{connector_type: 'github', display_name: 'GitHub', supports_live_mode: true}]})
  vi.spyOn(sources, 'getConnector').mockResolvedValue({supports_live_mode: true, supported_scopes: ['repository'], mapping_preview: []})
  const create = vi.spyOn(sources, 'createSource').mockResolvedValue({source_id: 'SRC-TEST'})
  vi.spyOn(sources, 'testSource').mockResolvedValue({status: 'HEALTHY', checks: {authentication: 'NOT_REQUIRED'}})
  const client = new QueryClient({defaultOptions: {queries: {retry: false}}})
  render(<QueryClientProvider client={client}><TechnicalModeProvider><MemoryRouter><AddSourcePage /></MemoryRouter></TechnicalModeProvider></QueryClientProvider>)
  await screen.findByRole('button', {name: /GitHub/})
  fireEvent.click(screen.getByRole('button', {name: 'Continue'}))
  fireEvent.change(screen.getByPlaceholderText('Northstar Engineering GitHub'), {target: {value: 'Neon samples'}})
  fireEvent.change(screen.getByRole('combobox', {name: 'Mode'}), {target: {value: 'live'}})
  fireEvent.change(screen.getByRole('textbox', {name: 'Public repository URL or owner/repo'}),
    {target: {value: 'https://github.com/neondatabase/postgres-sample-dbs'}})
  fireEvent.change(screen.getByRole('textbox', {name: 'Branch or commit SHA (optional)'}),
    {target: {value: 'b54cb67534bf20775803b181b7a1c6f573422161'}})
  fireEvent.click(screen.getByRole('button', {name: 'Continue'}))
  expect(screen.getByText('Public GitHub repositories can connect without a token.')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', {name: 'Continue'}))
  fireEvent.change(screen.getByRole('textbox', {name: 'Selected file paths (comma-separated)'}),
    {target: {value: 'dvdrental.sql'}})
  fireEvent.click(screen.getByRole('button', {name: 'Continue'}))
  fireEvent.click(screen.getByRole('button', {name: 'Continue'}))
  fireEvent.click(screen.getByRole('button', {name: 'Test connection'}))
  await waitFor(() => expect(create).toHaveBeenCalledOnce())
  expect(create.mock.calls[0][1]).toMatchObject({
    connector_type: 'github', connection_mode: 'live', credentials: {},
    connection_config: {settings: {repository: 'https://github.com/neondatabase/postgres-sample-dbs',
      ref: 'b54cb67534bf20775803b181b7a1c6f573422161', anonymous: true}},
    scope_config: {files: ['dvdrental.sql']},
  })
})

it('preserves selected SQL files when editing a registered source', async () => {
  vi.spyOn(sources, 'getSource').mockResolvedValue({source_id: 'SRC-TEST', display_name: 'Neon samples',
    connector_type: 'github', connection_mode: 'live', enabled: true,
    scope: {files: ['dvdrental.sql'], selected: []}, connection: {status: 'HEALTHY'},
    ingestion: {status: 'SUCCESS'}, credential: {configured: false}})
  vi.spyOn(sources, 'getSourceRuns').mockResolvedValue({items: []})
  const update = vi.spyOn(sources, 'updateSource').mockResolvedValue({})
  const client = new QueryClient({defaultOptions: {queries: {retry: false}}})
  render(<QueryClientProvider client={client}><TechnicalModeProvider><MemoryRouter initialEntries={['/sources/SRC-TEST']}>
    <Routes><Route path="/sources/:sourceId" element={<SourceDetailPage />} /></Routes>
  </MemoryRouter></TechnicalModeProvider></QueryClientProvider>)
  await screen.findByRole('heading', {name: 'Neon samples'})
  fireEvent.click(screen.getByRole('button', {name: 'configuration'}))
  fireEvent.click(screen.getByRole('button', {name: 'Save configuration'}))
  await waitFor(() => expect(update).toHaveBeenCalledOnce())
  expect(update.mock.calls[0][2].scope_config).toMatchObject({files: ['dvdrental.sql']})
})
