// The machinery behind a scripted demo video. Edit beats.mjs, not this file.
//
// One command starts the app, waits until it answers, drives it with human pacing, records, then
// trims and encodes. They share one process tree because inside a command sandbox the server and
// the browser must share a network namespace.
//
//   node demo/record.mjs
//
// Env: APP_CMD, APP_URL and SIZE override beats.mjs. HEADED=1 rehearses in a visible browser. SIZE
// defaults to 1920x1080, FPS to 30. BEATS=3 or BEATS=3-4 makes a short clip of those beats, counted
// from 1: the earlier beats still run, so the app reaches the right state, and are trimmed off.
// OUT is the output dir. Its default beside this file is out/, or out-clip/ with BEATS and
// out-rehearsal/ with HEADED, so a clip or a rehearsal can't replace the full take in out/.
//
// A take fails loud: any page error, a 5xx, a failed first-party request, a step timeout, or an app
// that exits gives a non-zero exit and no new video. The take is built in a staging dir beside OUT
// and moved in only once it is whole. A failed take leaves the previous good one in OUT, since that
// may be the only backup there is, and says so, so a stale video can't pass for this one.
import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_OUT = process.env.HEADED === '1' ? 'out-rehearsal' : process.env.BEATS ? 'out-clip' : 'out';
const OUT = path.resolve(process.env.OUT || path.join(HERE, DEFAULT_OUT));
const OUTPUTS = ['demo.mp4', 'captions.srt', 'steps.json'];
const LOOPBACK = new Set(['localhost', '127.0.0.1', '[::1]']);
const STEP_TIMEOUT_MS = 8000;
const BEAT_LIMIT_S = 60; // Catches what the step timeout can't, such as an evaluate that never returns.
const APP_WAIT_MS = 60000;
const HOLD_MS = 900; // Each caption stays up this long after its action, so a viewer can read the result.

let appProcess = null;
let appExit = null;
let stage = null;

// Runs inside the page, on every load, so the cursor and caption survive a reload through
// sessionStorage. Mouse events over an iframe don't reach the top page, so the dot pauses there.
function overlay({ x, y }) {
  if (window !== window.top) return;
  const add = () => {
    if (document.getElementById('__demo_cursor')) return;
    const cursor = document.createElement('div');
    cursor.id = '__demo_cursor';
    cursor.style.cssText = 'position:fixed;left:0;top:0;width:22px;height:22px;border-radius:50%;background:#0008;border:2px solid #fff;z-index:2147483647;pointer-events:none;transform:translate(-50%,-50%);transition:width .1s,height .1s';
    document.documentElement.append(cursor);
    const at = JSON.parse(sessionStorage.getItem('__demo_at') || JSON.stringify([x, y]));
    cursor.style.left = at[0] + 'px';
    cursor.style.top = at[1] + 'px';
    addEventListener('mousemove', e => {
      cursor.style.left = e.clientX + 'px';
      cursor.style.top = e.clientY + 'px';
      sessionStorage.setItem('__demo_at', JSON.stringify([e.clientX, e.clientY]));
    }, true);
    addEventListener('mousedown', () => { cursor.style.width = cursor.style.height = '14px'; }, true);
    addEventListener('mouseup', () => { cursor.style.width = cursor.style.height = '22px'; }, true);
    const box = document.createElement('div');
    box.id = '__demo_caption';
    box.style.cssText = 'position:fixed;left:50%;bottom:48px;transform:translateX(-50%);max-width:80%;padding:12px 24px;border-radius:10px;background:#000c;color:#fff;font:600 32px/1.3 system-ui,sans-serif;z-index:2147483646;pointer-events:none;opacity:0;transition:opacity .15s';
    document.documentElement.append(box);
    const caption = sessionStorage.getItem('__demo_caption');
    if (caption) { box.textContent = caption; box.style.opacity = 1; }
  };
  if (document.documentElement) add(); else addEventListener('DOMContentLoaded', add);
}

const setCaption = (page, text) => page.evaluate(caption => {
  const box = document.getElementById('__demo_caption');
  if (!box) throw new Error('the caption box is gone: the app replaced the whole document');
  box.textContent = caption;
  box.style.opacity = caption ? 1 : 0;
  sessionStorage.setItem('__demo_caption', caption);
}, text);

// What a beat's action receives. A target is a selector string or a Playwright locator.
function helpers(page) {
  const find = target => (typeof target === 'string' ? page.locator(target).first() : target);
  const glide = async target => {
    const element = find(target);
    await element.waitFor();
    await element.scrollIntoViewIfNeeded();
    const box = await element.boundingBox();
    if (!box) throw new Error('nothing to move to: ' + target);
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: 30 });
    await page.waitForTimeout(200);
  };
  const click = async target => {
    await glide(target);
    await page.mouse.down();
    await page.mouse.up();
  };
  const type = async (target, text) => {
    await click(target);
    await page.keyboard.type(text, { delay: 70 });
  };
  return { page, glide, click, type };
}

function parseSize(text) {
  const match = /^(\d+)x(\d+)$/.exec(text);
  const [width, height] = match ? [Number(match[1]), Number(match[2])] : [0, 0];
  if (!width || !height || width % 2 || height % 2) {
    throw new Error(`SIZE must be WIDTHxHEIGHT with even numbers (yuv420p needs them), got "${text}"`);
  }
  return { width, height };
}

function parseFps(text) {
  if (!/^[1-9]\d*$/.test(text)) throw new Error(`FPS must be a whole number above 0, got "${text}"`);
  return text;
}

function parseBeatRange(text, count) {
  if (!text) return [1, count];
  const match = /^(\d+)(?:-(\d+))?$/.exec(text);
  const first = Number(match?.[1]);
  const last = Number(match?.[2] ?? match?.[1]);
  if (!match || first < 1 || last < first || last > count) {
    throw new Error(`BEATS must be N or N-M within 1-${count}, got "${text}"`);
  }
  return [first, last];
}

function checkBeats(project) {
  const { app, beats } = project;
  if (typeof app?.cmd !== 'string' || typeof app?.url !== 'string') throw new Error('beats.mjs must export app = { cmd, url }');
  if (!Array.isArray(beats) || !beats.length) throw new Error('beats.mjs must export a non-empty beats list');
  for (const beat of beats) {
    if (typeof beat?.caption !== 'string' || typeof beat?.act !== 'function') {
      throw new Error('every beat needs a caption string and an act function: ' + JSON.stringify(beat));
    }
  }
}

async function loadChromium() {
  try {
    return (await import('playwright')).chromium;
  } catch (e) {
    throw new Error(`playwright won't load (${e.code || e.message}). Install a pinned version: npm i -D playwright@<version>`);
  }
}

// Checked first, so an old ffmpeg can't waste a whole take. Homebrew's ffmpeg has all of this.
function checkFfmpeg() {
  const probe = spawnSync('ffmpeg', ['-v', 'error', '-f', 'lavfi', '-i', 'color=s=16x16:d=0.1',
    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-fps_mode', 'cfr', '-f', 'null', '-'], { encoding: 'utf8' });
  if (probe.status !== 0) {
    throw new Error(`ffmpeg 5.1 or later with libx264 is needed (-fps_mode arrived in 5.1): ${probe.error?.message || probe.stderr.trim()}`);
  }
}

function withLimit(promise, ms, message) {
  let timer;
  const limit = new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(message)), ms); });
  return Promise.race([promise, limit]).finally(() => clearTimeout(timer));
}

async function answers(url) {
  try {
    return await fetch(url, { signal: AbortSignal.timeout(2000) });
  } catch {
    return null;
  }
}

function startApp(cmd) {
  const log = fs.openSync(path.join(stage, 'app.log'), 'a');
  appProcess = spawn(cmd, { shell: true, stdio: ['ignore', log, log], detached: true });
  fs.closeSync(log);
  appProcess.on('exit', (code, signal) => { appExit = signal ?? code; });
  appProcess.on('error', e => { appExit = e.message; });
}

async function waitUntilUp(url) {
  const deadline = Date.now() + APP_WAIT_MS;
  while (Date.now() < deadline) {
    if (appExit !== null) throw new Error(`the app exited (${appExit}) before it answered at ${url}`);
    if ((await answers(url))?.ok) return;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error(`the app never answered at ${url} within ${APP_WAIT_MS / 1000} s`);
}

// The app runs in its own process group, so a child of a wrapper such as npm goes with it.
function signalApp(signal) {
  if (!appProcess?.pid) return false;
  try { process.kill(-appProcess.pid, signal); return true; } catch { return false; }
}

async function stopApp() {
  signalApp('SIGTERM');
  const deadline = Date.now() + 3000;
  while (Date.now() < deadline && signalApp(0)) await new Promise(resolve => setTimeout(resolve, 50));
  signalApp('SIGKILL');
  appProcess = null;
}

const srtTime = seconds => new Date(Math.max(0, seconds) * 1000).toISOString().slice(11, 23).replace('.', ',');

function writeSidecars(steps, lead, trim, warnings) {
  const cues = steps.filter(step => step.caption);
  const srt = cues.map((step, i) => `${i + 1}\n${srtTime(step.start - trim)} --> ${srtTime(step.end - trim)}\n${step.caption}\n`);
  fs.writeFileSync(path.join(stage, 'captions.srt'), srt.join('\n'));
  fs.writeFileSync(path.join(stage, 'steps.json'), JSON.stringify({ lead, trim, steps, warnings }, null, 1));
}

function encode(webm, trim, fps) {
  const result = spawnSync('ffmpeg', ['-y', '-loglevel', 'error', '-ss', String(trim), '-i', webm,
    '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p', '-r', fps, '-fps_mode', 'cfr',
    '-movflags', '+faststart', '-an', path.join(stage, 'demo.mp4')], { stdio: 'inherit' });
  if (result.status !== 0) throw new Error(`ffmpeg failed: ${result.error?.message || 'exit ' + result.status}`);
}

function publish() {
  fs.mkdirSync(OUT, { recursive: true });
  for (const name of OUTPUTS) fs.renameSync(path.join(stage, name), path.join(OUT, name));
  fs.rmSync(stage, { recursive: true, force: true });
  stage = null;
}

async function record() {
  const project = await import(new URL('./beats.mjs', import.meta.url));
  checkBeats(project);
  const size = parseSize(process.env.SIZE || project.size || '1920x1080');
  const fps = parseFps(process.env.FPS || '30');
  const [firstBeat, lastBeat] = parseBeatRange(process.env.BEATS, project.beats.length);
  const chromium = await loadChromium();
  checkFfmpeg();
  const url = process.env.APP_URL || project.app.url;
  const appHost = new URL(url).hostname;
  const requiredHosts = new Set(project.requiredHosts ?? []);

  fs.mkdirSync(path.dirname(OUT), { recursive: true });
  stage = fs.mkdtempSync(OUT + '.take-');
  if (await answers(url)) throw new Error(`something already answers at ${url}: stop it, or point APP_URL elsewhere`);
  startApp(process.env.APP_CMD || project.app.cmd);
  await waitUntilUp(url);

  const problems = [];
  const warnings = [];
  // A font CDN failing shouldn't kill a take. The app's own host, any local port, and hosts the
  // project lists in requiredHosts should.
  const report = (requestUrl, message) => {
    const host = new URL(requestUrl).hostname;
    if (host === appHost || LOOPBACK.has(host) || requiredHosts.has(host)) {
      problems.push(message);
    } else {
      warnings.push(message);
      console.warn('warning, third-party request:', message);
    }
  };
  const troubles = () => [...problems, ...(appExit !== null ? [`the app exited during the take (${appExit})`] : [])];

  const browser = await chromium.launch({ headless: process.env.HEADED !== '1' });
  try {
    const context = await browser.newContext({ viewport: size, recordVideo: { dir: stage, size } });
    await context.addInitScript(overlay, { x: size.width / 2, y: 200 });
    const page = await context.newPage();
    const t0 = Date.now(); // The video starts with the page, so the trim and the captions count from here.
    const elapsed = () => (Date.now() - t0) / 1000;
    page.setDefaultTimeout(STEP_TIMEOUT_MS);
    page.on('pageerror', e => problems.push('page error: ' + e.message));
    page.on('response', r => { if (r.status() >= 500) report(r.url(), `HTTP ${r.status()} ${r.url()}`); });
    page.on('requestfailed', r => {
      // ERR_ABORTED is the page cancelling its own request (a reload, an AbortController), not a failure.
      const reason = r.failure()?.errorText;
      if (reason !== 'net::ERR_ABORTED') report(r.url(), `request failed: ${r.url()} (${reason})`);
    });

    const opened = await page.goto(url);
    if (!opened?.ok()) throw new Error(`${url} answered ${opened?.status()} in the browser`);
    await page.mouse.move(size.width / 2, 200);
    const lead = elapsed();

    const kit = helpers(page);
    const steps = [];
    for (const [index, { caption, act, limit = BEAT_LIMIT_S }] of project.beats.slice(0, lastBeat).entries()) {
      const start = elapsed();
      try {
        await setCaption(page, caption);
        await withLimit(act(kit), limit * 1000, `ran past its ${limit} s limit`);
        await page.waitForTimeout(HOLD_MS);
      } catch (e) {
        throw new Error(`beat "${caption}": ${[...troubles(), e.message].join('; ')}`);
      }
      if (troubles().length) throw new Error(`beat "${caption}": ${troubles().join('; ')}`);
      if (index + 1 >= firstBeat) steps.push({ caption, start, end: elapsed() });
    }

    const webm = await page.video().path();
    await context.close();
    await browser.close();
    if (troubles().length) throw new Error(troubles().join('; '));

    const trim = firstBeat > 1 ? steps[0].start : Math.max(0, lead - 0.2);
    writeSidecars(steps, lead, trim, warnings);
    encode(webm, trim, fps);
    publish();
    console.log(`${path.join(OUT, 'demo.mp4')}: ${(steps.at(-1).end - trim).toFixed(1)} s across ${steps.length} beats`);
  } finally {
    await withLimit(browser.close(), 5000, 'browser close').catch(() => {});
  }
}

function explainFailure(error) {
  console.error('recording failed:', error.message);
  const log = stage && path.join(stage, 'app.log');
  if (log && fs.existsSync(log)) {
    const tail = fs.readFileSync(log, 'utf8').trimEnd().split('\n').slice(-20).join('\n');
    if (tail) console.error('--- last lines of the app\'s output ---\n' + tail);
  }
}

// The backstop for a signal or an uncaught error: no app left running, no half-built take.
process.on('exit', () => {
  signalApp('SIGTERM');
  if (stage) fs.rmSync(stage, { recursive: true, force: true });
});
for (const [signal, number] of [['SIGINT', 2], ['SIGTERM', 15], ['SIGHUP', 1]]) {
  process.on(signal, () => process.exit(128 + number));
}

let exitCode = 0;
try {
  await record();
} catch (e) {
  explainFailure(e);
  if (fs.existsSync(path.join(OUT, 'demo.mp4'))) {
    console.error(`this take failed: ${path.join(OUT, 'demo.mp4')} is the previous take, unchanged`);
  }
  exitCode = 1;
}
await stopApp();
process.exit(exitCode);
