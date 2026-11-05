// The part a project edits: how to start the app, and the demo as a list of beats. record.mjs loads
// this file and does the rest. The example drives a plain to-do list. Replace it with your script.

export const app = {
  // Starts the app and keeps running. record.mjs stops it at the end. APP_CMD overrides. Use '' for an
  // app already running elsewhere (deployed, on a board): the take neither starts nor stops it.
  cmd: 'npm start',
  url: 'http://127.0.0.1:3000/', // The page to open. The take starts once it answers. APP_URL overrides.
};

// The video's size and frame rate, when the event asks for something other than 1920x1080 at 30.
// SIZE and FPS override.
// export const size = '1280x720';
// export const fps = 24;

// For an app on a self-signed certificate, such as a board on the LAN:
// export const ignoreHTTPSErrors = true;

// A failed request to the app's own host or any local port kills a take. Other hosts only warn, so a
// font CDN can't ruin one. List an outside host here when the demo depends on it.
export const requiredHosts = [];

// Each beat shows its caption, runs its action, then holds about a second. An action gets:
//   glide(target)        move the cursor there at a human pace
//   click(target)        glide, then click
//   type(target, text)   click, then type at a human pace
//   page                 the Playwright page, for waits, keys and assertions
// A target is a selector string or a Playwright locator. Each wait gives up after 8 s and fails the
// take, so end an action by waiting for what the viewer should see. A step that is genuinely slow
// gets a longer wait on that one line: `.waitFor({ timeout: 15000 })`. A beat that runs longer than
// 60 s in total fails too: add `limit: <seconds>` to allow more. An empty caption hides the box.
export const beats = [
  {
    caption: 'A plain to-do list, kept on a real server',
    act: async ({ page }) => {
      await page.waitForTimeout(1500);
    },
  },
  {
    caption: 'Add an item',
    act: async ({ page, type, click }) => {
      await type('#new-item', 'Buy stamps');
      await click('button');
      await page.getByText('Buy stamps').waitFor();
    },
  },
  {
    caption: 'Tick it off, and the count follows',
    act: async ({ page, click }) => {
      await click('li input');
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
