// The beats for the fixture app, about 14 s long. The test overrides the URL with a free port.
export const app = { cmd: 'node server.mjs', url: 'http://127.0.0.1:4173/' };

export const beats = [
  {
    caption: 'A plain to-do list, kept on a real server',
    act: async ({ page }) => { await page.waitForTimeout(1500); },
  },
  {
    caption: 'Type one in',
    act: async ({ type }) => { await type('#new-item', 'Buy stamps'); },
  },
  {
    caption: 'Add it',
    act: async ({ page, click }) => {
      await click('button');
      await page.getByText('Buy stamps').waitFor();
    },
  },
  {
    caption: 'And another',
    act: async ({ page, type }) => {
      await type('#new-item', 'Return the library book');
      await page.keyboard.press('Enter');
      await page.getByText('Return the library book').waitFor();
    },
  },
  {
    caption: 'Tick one off, and the count follows',
    act: async ({ page, click }) => {
      await click('li:first-child input');
      await page.locator('li.done').waitFor();
    },
  },
  {
    caption: 'Reload: the server kept it',
    act: async ({ page }) => {
      await page.reload();
      await page.locator('li.done').waitFor();
      await page.waitForTimeout(800);
    },
  },
];
