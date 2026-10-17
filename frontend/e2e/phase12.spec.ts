import { expect, test } from '@playwright/test'

const apiHeaders={Authorization:'Bearer test-admin-token','X-Tenant-ID':'northstar'}

test('Phase 12 live frontend story uses the real Phase 11 API', async ({ page, request }) => {
  const consoleErrors:string[]=[]
  page.on('console',msg=>{if(msg.type()==='error')consoleErrors.push(msg.text())})
  await test.step('open application and backend-derived situations', async()=>{
    await page.goto('/situations')
    await expect(page.getByRole('heading',{name:'Situations'})).toBeVisible()
    await expect(page.getByText('INC-001')).toBeVisible()
  })
  await test.step('open canonical situation context', async()=>{
    await page.getByRole('link',{name:'INC-001'}).click()
    await expect(page).toHaveURL(/\/situations\/INC-001/)
    await expect(page.getByText('Context graph')).toBeVisible()
    await expect(page.locator('[aria-label="Interactive graph"]')).toBeVisible()
  })
  await test.step('create investigation from the UI', async()=>{
    await page.getByPlaceholder('Question or investigation goal').fill('Why did Checkout fail during DPL-882?')
    await page.getByRole('button',{name:'Run Investigation'}).click()
    await expect(page).toHaveURL(/\/investigations\//)
    await expect(page.getByRole('heading',{name:'Investigation'})).toBeVisible()
  })
  await test.step('run graph-first retrieval and expose scope/provenance', async()=>{
    await page.getByPlaceholder('Evidence query').fill('region_scope cannot be null')
    await page.getByRole('button',{name:'Retrieve'}).click()
    await expect(page.getByText('Graph scope')).toBeVisible()
    await expect(page.getByText('Retrieval results')).toBeVisible()
    await expect(page.locator('pre').filter({hasText:'evidence_ids'}).first()).toBeVisible()
  })
  await test.step('inspect Evidence provenance', async()=>{
    await page.goto('/evidence/E-003')
    await expect(page.getByRole('heading',{name:/Evidence E-003/})).toBeVisible()
    await expect(page.getByText('Provenance',{exact:true})).toBeVisible()
  })
  await test.step('inspect conflicting Claim and backend authority resolution', async()=>{
    await page.goto('/claims/C-001')
    await expect(page.getByRole('heading',{name:/Claim C-001/})).toBeVisible()
    await page.getByPlaceholder('Subject entity ID').fill('INC-001')
    await page.getByRole('button',{name:'Resolve'}).click()
    await expect(page.locator('pre').filter({hasText:'selected_claim_id'})).toBeVisible()
  })
  await test.step('generate plan and inspect Task DAG', async()=>{
    await page.goto('/work?tab=plans')
    const fields=page.locator('.panel').filter({hasText:'Create plan'})
    await fields.getByLabel('Situation ID').fill('INC-001')
    await fields.getByRole('button',{name:'Generate plan'}).click()
    const open=page.getByRole('link',{name:/Open generated plan/})
    await expect(open).toBeVisible(); await open.click()
    await expect(page.getByText('Task DAG')).toBeVisible()
    await expect(page.locator('[aria-label="Interactive graph"]')).toBeVisible()
  })
  await test.step('inspect task blackboard and Agent', async()=>{
    await page.goto('/work?tab=tasks&task=TASK-P12-ACCEPT')
    await expect(page.getByText('Task detail')).toBeVisible()
    await expect(page.getByText('Coordination state')).toBeVisible()
    await page.goto('/work?tab=agents')
    await expect(page.getByText('AGENT-P6-INVESTIGATOR')).toBeVisible()
  })
  await test.step('inspect decision genealogy and governance', async()=>{
    await page.goto('/decisions/DEC-INC001-ROLLBACK')
    await expect(page.getByText(/Evidence → Claims → Decision/)).toBeVisible()
    await page.getByPlaceholder('Action ID').fill('ACT-ROLLBACK-MIG203')
    await expect(page.getByText('Governance')).toBeVisible()
  })
  await test.step('blast radius and explicit graph paths', async()=>{
    await page.goto('/entities/SYS-PRICING-API?tab=blast-radius&depth=3')
    await expect(page.getByText('Blast-radius result')).toBeVisible()
    await expect(page.locator('[aria-label="Interactive graph"]')).toBeVisible()
  })
  await test.step('counterfactual is explicitly non-mutating', async()=>{
    await page.goto('/simulations')
    await expect(page.getByText('SIMULATION ONLY.')).toBeVisible()
    await page.getByLabel('Situation').fill('INC-001')
    await page.getByLabel('Source entity').fill('SYS-CHECKOUT')
    await page.getByLabel('Target entity').fill('SYS-PRICING-API')
    await page.getByRole('button',{name:'Run Simulation'}).click()
    await expect(page.getByText('Before / after')).toBeVisible()
  })
  await test.step('Company Brain process semantics and analytics', async()=>{
    await page.goto('/company-brain?tab=processes')
    await page.getByLabel('Process scope ID').fill('INC-001')
    await expect(page.getByText('Timeline semantics')).toBeVisible()
    await expect(page.locator('pre').filter({hasText:'BEFORE'})).toBeVisible()
    await page.getByRole('button',{name:'policy-drift'}).click()
    await page.getByLabel('Policy ID').fill('POL-DB-04')
    await expect(page.getByText('Policy-vs-practice drift')).toBeVisible()
    await expect(page.locator('pre').filter({hasText:'ACT-COMPAT-TEST'})).toBeVisible()

    await page.getByRole('button',{name:'commitments'}).click()
    await expect(page.locator('pre').filter({hasText:'COM-017'})).toBeVisible()

    await page.getByRole('button',{name:'ownership-gaps'}).click()
    await expect(page.getByText('Ownership gaps')).toBeVisible()

    await page.getByRole('button',{name:'expertise'}).click()
    await expect(page.locator('pre').filter({hasText:'PERSON-RIYA'})).toBeVisible()
    await expect(page.locator('pre').filter({hasText:'SYS-PRICING-DB'})).toBeVisible()

    await page.getByRole('button',{name:'bus-factor'}).click()
    await expect(page.getByText('Bus factor')).toBeVisible()

    await page.getByRole('button',{name:'bottlenecks'}).click()
    await expect(page.getByText('Bottlenecks')).toBeVisible()

    await page.getByRole('button',{name:'bridges'}).click()
    await expect(page.getByText('Bridge risks')).toBeVisible()

    await page.getByRole('button',{name:'duplicate-initiatives'}).click()
    await expect(page.locator('pre').filter({hasText:'PROJ-REFUND-A'})).toBeVisible()
    await expect(page.locator('pre').filter({hasText:'PROJ-REFUND-B'})).toBeVisible()
  })
  await test.step('anomaly view renders backend motif', async()=>{
    await page.goto('/anomalies')
    await expect(page.getByRole('heading',{name:'Anomalies'})).toBeVisible()
    await expect(page.getByRole('button',{name:'FRONTEND_DIRECT_DATABASE'})).toBeVisible()
    await page.getByRole('button',{name:'FRONTEND_DIRECT_DATABASE'}).click()
    await expect(page.getByText('Abnormal vs expected motif')).toBeVisible()
    await expect(page.locator('pre').filter({hasText:'frontend -> service/api -> database'})).toBeVisible()
  })
  await test.step('backend connectivity proof: external API state change appears after refresh', async()=>{
    const id=`INC-P12-LIVE-${Date.now()}`
    const response=await request.post('http://127.0.0.1:8000/api/v1/situations',{headers:{...apiHeaders,'Content-Type':'application/json','Idempotency-Key':`p12-${id}`},data:{situation_id:id,name:'Phase12 live connectivity proof',description:'Created during Playwright acceptance',severity:'LOW'}})
    expect(response.status()).toBe(201)
    await page.goto('/situations')
    await expect(page.getByText(id)).toBeVisible()
  })
  expect(consoleErrors, `fatal browser console errors: ${consoleErrors.join(' | ')}`).toEqual([])
})

test('read-only principal cannot enable governed mutation controls', async ({ page }) => {
  await page.addInitScript(()=>localStorage.setItem('graphhacks.phase12.api',JSON.stringify({baseUrl:'',token:'test-reader-token',tenantId:'northstar'})))
  await page.goto('/work?tab=plans')
  await expect(page.getByRole('button',{name:'Generate plan'})).toBeDisabled()
  await page.goto('/evidence/E-003')
  await expect(page.getByRole('button',{name:'Invalidate'})).toBeDisabled()
})
