import {expect,test} from '@playwright/test'

test('Demo Lab shows three tracks, guided steps and self-reported progress',async({page})=>{
 await page.goto('/demo')
 await expect(page.getByRole('heading',{name:'Demo & Scenario Explorer'})).toBeVisible()
 await expect(page.getByText('Company Brain',{exact:true}).first()).toBeVisible()
 await expect(page.getByRole('heading',{name:'Guided organizational walkthrough'})).toBeVisible()
 await page.getByRole('checkbox',{name:'I inspected this stage'}).first().check()
 await expect(page.getByText('Stages self-marked inspected').first()).toBeVisible()
 await page.getByRole('button',{name:'Acceptance & capabilities'}).click()
 await expect(page.getByRole('heading',{name:'Scenario acceptance matrix'})).toBeVisible()
 await expect(page.getByText('NOT VERIFIED LIVE').first()).toBeVisible()
})

test('scenario links open a stable guided route without IDs being entered',async({page})=>{
 await page.goto('/scenarios')
 await page.getByRole('link',{name:'Guided walkthrough and trace ↗'}).first().click()
 await expect(page).toHaveURL(/\/demo\?scenario=AST-/)
 await expect(page.getByRole('heading',{name:'Guided organizational walkthrough'})).toBeVisible()
})
