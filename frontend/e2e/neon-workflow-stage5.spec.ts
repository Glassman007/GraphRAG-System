import { expect, test } from '@playwright/test'

test('new Sources registration is discoverable and explorable in Company Brain', async ({ page }) => {
  const sourceId = process.env.STAGE5_SOURCE_ID
  test.skip(!sourceId, 'Stage 5 isolated source ID is required')
  await page.goto('/sources')
  const card = page.locator('.source-card').filter({hasText: 'Neon DVD rental downstream'})
  await expect(card).toBeVisible()
  await card.click()
  await expect(page).toHaveURL(new RegExp(`/sources/${sourceId}$`))
  await expect(page.getByRole('heading', {name: 'Neon DVD rental downstream'})).toBeVisible()
  await page.getByRole('link', {name: 'Explore this source in Company Brain'}).click()
  await expect(page).toHaveURL(/company-brain\?tab=sql-schema&source_id=/)
  await expect(page.getByLabel('Interactive graph')).toBeVisible()
  await page.getByPlaceholder('Name or ID').fill('public.payment')
  await page.getByRole('button', {name: 'Find', exact: true}).click()
  await expect(page.getByRole('heading', {name: 'public.payment'})).toBeVisible()
  await expect(page.getByRole('link', {name: /Source line/}).first()).toHaveAttribute('href',
    /github\.com\/neondatabase\/postgres-sample-dbs\/blob\/b54cb67534bf20775803b181b7a1c6f573422161\/dvdrental\.sql#L\d+/)
  await page.getByRole('button', {name: 'To public.rental'}).click()
  await expect(page.getByRole('heading', {name: 'public.rental'})).toBeVisible()
  await page.getByRole('button', {name: 'To public.inventory'}).click()
  await expect(page.getByRole('heading', {name: 'public.inventory'})).toBeVisible()
  await page.getByRole('button', {name: 'To public.film'}).click()
  await expect(page.getByRole('heading', {name: 'public.film'})).toBeVisible()
})
