import { expect,test } from '@playwright/test'
test('Phase 12 capabilities remain reachable after Phase 13 presentation changes',async({page})=>{
 await page.goto('/situations');await expect(page.getByRole('heading',{name:/Situations|Build your Company Brain/})).toBeVisible()
 await page.goto('/company-brain');await expect(page.getByRole('heading',{name:'Company Brain'})).toBeVisible()
 await page.goto('/simulations');await expect(page.getByText('SIMULATION ONLY.')).toBeVisible()
 await page.goto('/anomalies');await expect(page.getByRole('heading',{name:'Anomalies'})).toBeVisible()
})
