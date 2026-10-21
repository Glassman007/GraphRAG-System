import { expect, test, type Page } from '@playwright/test'

// UI-contract tests deliberately mock read APIs. They verify actual browser
// interaction but NEVER claim to certify FalkorDB, a model, or a live worker.
const runId = 'SRUN-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'
const workspace = {
  id: runId, goal: 'Investigate the route outage and verify the dependency',
  owner: 'browser-test', source_entity_id: 'INC-AST-ROUTE-OUTAGE',
  status: 'PAUSED', created_at: '2026-10-18T08:00:00Z',
  updated_at: '2026-10-18T08:02:00Z', execution_mode: 'MODEL_CONSENT_REQUIRED',
  recovery_available: true,
}
const supervisor = {
  id: runId, status: 'PAUSED', answer: 'Route dependency requires renewed verification.',
  citations: ['SYS-AST-ROUTE-DB'], knowledge_gaps: ['Confirm deployment window'],
  tasks: [
    { id: 'TASK-DEPEND', objective: 'Inspect dependency records', capability: 'DEPENDENCY_ANALYSIS',
      depends_on: [], status: 'COMPLETED', agent_id: 'dependency-analyst', attempts: 1,
      result: { summary: 'Sourced dependency found', confidence: 'VERIFIED', risk: 'LOW', citations: ['SYS-AST-ROUTE-DB'], knowledge_gaps: [], requires_human_review: false } },
    { id: 'TASK-VERIFY', objective: 'Check the dependency provenance', capability: 'EVIDENCE_VERIFICATION',
      depends_on: ['TASK-DEPEND'], status: 'PENDING', agent_id: 'policy-verifier', attempts: 0 },
  ],
  events: [{ event_index: 1, kind: 'TASK_COMPLETED', summary: 'Dependency evidence recorded',
    task_id: 'TASK-DEPEND', agent_id: 'dependency-analyst', status: 'COMPLETED', created_at: '2026-10-18T08:02:00Z' }],
  conflicts: [], escalations: [], tokens_used: 120,
}

async function mockWorkspace(page: Page, populated: boolean) {
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url())
    const path = url.pathname
    let value: unknown
    if (path === '/api/v1/session') value = { subject: 'browser-test', tenant_id: 'asteria', permissions: ['ADMIN'] }
    else if (path === '/api/v1/ready') value = { ready: true }
    else if (path.endsWith('/workspace/capabilities')) value = {
      status: 'PARTIAL', provider: 'not-configured', model_configured: false,
      worker_durability: 'PROCESS_LOCAL', controls: 'COOPERATIVE', external_action_auto_execution: false,
    }
    else if (path.endsWith('/workspace/runs') && route.request().method() === 'GET') value = { items: populated ? [workspace] : [] }
    else if (path.endsWith('/workspace/runs/' + runId)) value = {
      workspace, supervisor, checkpoint: { revision: 3, status: 'PAUSED', updated_at: workspace.updated_at,
        reactive_affected_tasks: ['TASK-VERIFY'] }, comparison: [], snapshots: [], classification: 'RECORDED',
    }
    else if (path.endsWith('/workspace/changes')) value = { items: [{ id: 'CHANGE-1', status: 'CONFIRMED',
      kind: 'RELATIONSHIP_CHANGED', changed_ids: ['SYS-AST-ROUTE-DB'],
      created_at: '2026-10-18T08:04:00Z', workflow_impacts: [{ run_id: runId,
        affected_task_ids: ['TASK-VERIFY'], status: 'NEEDS_REVIEW' }] }] }
    else if (path.endsWith('/governed/tools')) value = { tools: [], policy: 'DENY_UNCONFIGURED' }
    else if (path.endsWith('/governed/actions')) value = { items: [] }
    else if (path.endsWith('/memory/search')) value = { items: [{ id: 'MEM-1', subject_id: 'SYS-AST-ROUTE-DB',
      predicate: 'DEPENDS_ON', value: 'SYS-AST-ROUTE-API', status: 'VERIFIED',
      scope: 'SHARED', citations: ['SYS-AST-ROUTE-DB'], origin_run_id: runId,
      verified_by: 'verifier-agent', source_tools: ['graph-neighbors'] }], count: 1 }
    else value = { error: { code: 'MOCK_NOT_IMPLEMENTED', message: 'UI contract test did not stub ' + path } }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(value) })
  })
}

test('UI_CONTRACT: command form requires explicit model consent and scenario selection only fills fields', async ({ page }) => {
  await mockWorkspace(page, false)
  await page.goto('/agent-workspace')
  await expect(page.getByRole('heading', { name: 'One objective. One workspace.' })).toBeVisible()
  const start = page.getByRole('button', { name: /^Start investigation/i })
  await expect(start).toBeDisabled()
  await page.getByRole('checkbox', { name: /I authorize sending the scoped organizational context/i }).check()
  await expect(start).toBeEnabled()
  await page.getByText('Asteria scenario shortcuts').click()
  await expect(page.locator('.aw-scenario-list button').first()).toBeVisible()
  await page.locator('.aw-scenario-list button').first().click()
  await expect(page.getByText('Selected fixture:')).toBeVisible()
  await expect(page.getByText('No workspace runs yet.')).toBeVisible()
  // Do NOT click Start: this fixture tests UI contracts, not external execution.
})

test('UI_CONTRACT: task dependencies, replay, memory, changes, and governance are inspectable', async ({ page }) => {
  await mockWorkspace(page, true)
  await page.goto('/agent-workspace')
  await expect(page.getByRole('heading', { name: 'Specialist task graph' })).toBeVisible()
  await expect(page.getByRole('group', { name: 'Interactive dependency task graph' }).getByRole('button')).toHaveCount(2)
  await page.getByRole('button', { name: /TASK-DEPEND COMPLETED/ }).click()
  await expect(page.getByText('Sourced dependency found')).toBeVisible()
  await expect(page.getByText('Dependency evidence recorded')).toBeVisible()
  await expect(page.getByText('Targeted re-verification required')).toBeVisible()
  await page.getByRole('navigation', { name: 'Workspace inspections' }).getByRole('button', { name: 'Memory' }).click()
  await page.getByRole('button', { name: 'Search this investigation context' }).click()
  await expect(page.getByText('SYS-AST-ROUTE-DB / DEPENDS_ON')).toBeVisible()
  await page.getByRole('navigation', { name: 'Workspace inspections' }).getByRole('button', { name: 'Replay / compare' }).click()
  await expect(page.getByRole('heading', { name: 'What happened, and when?' })).toBeVisible()
  await page.getByRole('navigation', { name: 'Workspace inspections' }).getByRole('button', { name: 'Change feed' }).click()
  await expect(page.getByText('RELATIONSHIP_CHANGED', { exact: true })).toBeVisible()
  await page.getByRole('navigation', { name: 'Workspace inspections' }).getByRole('button', { name: 'Approvals / actions' }).click()
  await expect(page.getByRole('heading', { name: 'Review, approve, verify' })).toBeVisible()
  // No approval or action is sent by this UI read-only fixture.
})

test('LIVE_BACKEND: workspace read APIs and navigation work without starting agents', async ({ page, request }) => {
  test.skip(process.env.GRAPH_HACKS_BROWSER_LIVE !== '1', 'Explicit live backend mode only')
  const headers = {
    Authorization: `Bearer ${process.env.VITE_TEST_TOKEN || 'test-asteria-admin-token'}`,
    'X-Tenant-ID': process.env.VITE_TENANT_ID || 'asteria',
  }
  const response = await request.get('/api/v1/agent-runtime/workspace/runs', { headers })
  expect(response.status()).toBe(200)
  expect(Array.isArray((await response.json()).items)).toBe(true)
  await page.goto('/agent-workspace')
  await expect(page.getByRole('heading', { name: 'One objective. One workspace.' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'What needs to be accomplished?' })).toBeVisible()
  // Read-only smoke; never starts a model run, authorizes a rollback or mutates graph.
})
