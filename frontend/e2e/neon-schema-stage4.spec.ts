import { expect, test } from '@playwright/test'

test('Company Brain explores persisted Neon foreign keys and GitHub evidence', async ({ page }) => {
  await page.goto('/company-brain?tab=sql-schema')
  await expect(page.getByRole('heading', {name: 'Company Brain'})).toBeVisible()
  await expect(page.getByLabel('Interactive graph')).toBeVisible()
  await page.getByPlaceholder('Name or ID').fill('public.payment')
  await page.getByRole('button', {name: 'Find', exact: true}).click()
  await expect(page.getByRole('heading', {name: 'public.payment'})).toBeVisible()
  await expect(page.getByText('payment_rental_id_fkey', {exact: false}).first()).toBeVisible()
  await expect(page.getByRole('link', {name: /Source line/}).first()).toHaveAttribute('href', /github\.com\/neondatabase\/postgres-sample-dbs\/blob\/b54cb67534bf20775803b181b7a1c6f573422161\/dvdrental\.sql#L\d+/)
  await page.getByRole('button', {name: 'To public.rental'}).click()
  await expect(page.getByRole('heading', {name: 'public.rental'})).toBeVisible()
  await page.getByRole('button', {name: 'To public.inventory'}).click()
  await expect(page.getByRole('heading', {name: 'public.inventory'})).toBeVisible()
  await page.getByRole('button', {name: 'To public.film'}).click()
  await expect(page.getByRole('heading', {name: 'public.film'})).toBeVisible()
})
