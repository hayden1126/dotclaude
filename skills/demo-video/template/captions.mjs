// MIT License
//
// Copyright (c) 2026 Chun Hei Leung
//
// Permission is hereby granted, free of charge, to any person obtaining a copy
// of this software and associated documentation files (the "Software"), to deal
// in the Software without restriction, including without limitation the rights
// to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
// copies of the Software, and to permit persons to whom the Software is
// furnished to do so, subject to the following conditions:
//
// The above copyright notice and this permission notice shall be included in all
// copies or substantial portions of the Software.
//
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
// IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
// FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
// AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
// LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
// OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
// SOFTWARE.

// Puts captions on a finished take, for viewers who watch muted: subtitles that repeat each spoken
// line, a short label per beat, and note boxes for extra detail. Text comes from beats.mjs (each
// beat's say, caption and note), timing from the take's steps.json.
//
//   node demo/captions.mjs          builds demo/out/demo-captioned.mp4 and demo/out/subtitles.srt
//   node demo/captions.mjs lines    lists each beat's time, label, said line and note, and flags a
//                                   line with more words than fit its beat at 2.3 words a second
//
// The build burns the captions into demo-voice.mp4 when it exists, otherwise into the silent
// demo.mp4. The sound is copied untouched; the picture is encoded again as record.mjs encodes it.
// Labels are drawn only when steps.json says labels 'after', since otherwise the page already drew
// them during the take.
//
// Env: OUT is the take's dir, by default out/ beside this file.
//
// A build fails loud, and a failed one leaves the last good files alone. A good one moves the files it
// replaces to demo-captioned.prev.mp4 and subtitles.prev.srt.
//
// Known limits: subtitles follow the beats' times, not the speech itself, so a line read early or late
// stays where its beat is. Glyphs come from the machine's fonts through fontconfig, so CJK text needs a
// CJK font installed.
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.resolve(process.env.OUT || path.join(HERE, 'out'));
const STEPS = path.join(OUT, 'steps.json');
const TAKE = path.join(OUT, 'demo.mp4');
const VOICED = path.join(OUT, 'demo-voice.mp4');
const RESULT = path.join(OUT, 'demo-captioned.mp4');
const PREVIOUS = path.join(OUT, 'demo-captioned.prev.mp4');
const SUBTITLES = path.join(OUT, 'subtitles.srt');
const SUBTITLES_PREVIOUS = path.join(OUT, 'subtitles.prev.srt');
const BUILDING = path.join(OUT, `.demo-captioned.${process.pid}.mp4`);
const SUBTITLES_BUILDING = path.join(OUT, `.subtitles.${process.pid}.srt`);
const WORDS_PER_SECOND = 2.3; // About as fast as a viewer reads a subtitle and a speaker talks calmly.
const LABEL_WORDS = 6;
const LINE_CHARS = 42; // A subtitle line, and at most two lines on screen at once.
const CUE_LINES = 2;
const NOTE_CHARS = 32; // A note box line, kept narrow so the box stays in its corner.
const PAGE_BOX_PX = 130; // record.mjs's in-page caption box: 48 px off the bottom, one line about 66 px tall.
const BOX = '&H40000000'; // Black, a quarter see-through (ASS colours are &HAABBGGRR, alpha 00 opaque).
const LABELS = ['page', 'after'];
const NOTE_PLACES = ['top-left', 'top', 'top-right', 'left', 'center', 'right', 'bottom-left', 'bottom', 'bottom-right'];
const SUBTITLE_PLACES = ['bottom', 'top'];
const ANCHOR = { 'bottom-left': 1, bottom: 2, 'bottom-right': 3, left: 4, center: 5, right: 6, 'top-left': 7, top: 8, 'top-right': 9 };
const SAFE_PATH = /^[A-Za-z0-9_./-]+$/; // Nothing ffmpeg's filter syntax reads: no : , ; ' \ [ ] = or space.
const WORD_JOINER = String.fromCharCode(0x2060);
const DRAWN_BELOW = 200; // Luma: a white test frame reads 235 with nothing on it, and about 70 under a caption box.

// As record.mjs computes it: what a beat did, so a swapped or rewritten beat can't pass for the take's.
// It reads the action's source, so an action made by a helper reads the same whatever the helper was given.
const actionPrint = act => createHash('sha256').update(String(act)).digest('hex').slice(0, 16);

let scratch = null;

const shown = file => path.relative(process.cwd(), file) || '.';
const rateOf = text => { const [top, bottom] = String(text).split('/').map(Number); return top / (bottom || 1); };
const words = text => String(text ?? '').trim().split(/\s+/).filter(Boolean);
const srtTime = seconds => new Date(Math.round(Math.max(0, seconds) * 1000)).toISOString().slice(11, 23).replace('.', ',');

// beats.mjs and steps.json come from the project, so text is printed with no control, line-separator
// or direction characters: it can't move the cursor, clear a line, reorder text or start a line that
// passes for something else. It also keeps a line break out of a subtitle or an ASS event.
export const plain = text => String(text).replace(/[\u0000-\u001f\u007f-\u009f\u200e\u200f\u2028\u2029\u202a-\u202e\u2066-\u2069]+/g, ' ');

// Text for an ASS event, shown as written. A backslash gets an invisible word joiner after it, so \N,
// \n, \h and every override tag stop being escapes, and a brace is escaped, so { } can't open an
// override block. With every backslash broken, even a libass too old to know \{ can't run a tag.
export const assText = text => plain(text).replace(/\\/g, '\\' + WORD_JOINER).replace(/[{}]/g, brace => '\\' + brace);

// Words into lines of at most `width` characters; a longer word gets a line of its own.
export function wrap(text, width) {
  const rows = [];
  for (const word of words(plain(text))) {
    if (rows.length && rows.at(-1).length + 1 + word.length <= width) rows[rows.length - 1] += ' ' + word;
    else rows.push(word);
  }
  return rows;
}

// A said line as subtitle cues of at most two lines, each timed by its share of the line's words across
// the beat.
export function subtitleCues(say, start, end) {
  const total = words(plain(say)).length;
  if (!total) return [];
  const rows = wrap(say, LINE_CHARS);
  const cues = [];
  let at = start;
  for (let index = 0; index < rows.length; index += CUE_LINES) {
    const lines = rows.slice(index, index + CUE_LINES);
    const share = lines.reduce((count, row) => count + words(row).length, 0) / total;
    const last = index + CUE_LINES >= rows.length;
    cues.push({ start: at, end: last ? end : at + share * (end - start), lines });
    at = cues.at(-1).end;
  }
  return cues;
}

// How a said line fits its beat: its words, how many fit, and how many are over.
export function density(say, seconds) {
  const count = words(say).length;
  const fit = Math.floor(WORDS_PER_SECOND * seconds);
  return { count, fit, over: Math.max(0, count - fit) };
}

function checkBeats(project) {
  const { beats } = project;
  if (!Array.isArray(beats) || !beats.length) throw new Error('beats.mjs must export a non-empty beats list');
  for (const [index, beat] of beats.entries()) {
    if (typeof beat?.caption !== 'string') throw new Error(`beat ${index + 1}: caption must be a string`);
    if (beat.say !== undefined && typeof beat.say !== 'string') throw new Error(`beat ${index + 1}: say must be a string`);
    const { note } = beat;
    if (note !== undefined && (typeof note?.text !== 'string' || !note.text.trim() || !NOTE_PLACES.includes(note.at))) {
      throw new Error(`beat ${index + 1}: note must be { text, at }, with text a string and at one of ${NOTE_PLACES.join(', ')}`);
    }
    if (beat.subtitleAt !== undefined && !SUBTITLE_PLACES.includes(beat.subtitleAt)) {
      throw new Error(`beat ${index + 1}: subtitleAt must be 'top' or 'bottom'`);
    }
    // As record.mjs checks it, so a refusal here never sends the user to a retake record.mjs refuses.
    if (beat.offCamera !== undefined && typeof beat.offCamera !== 'boolean') throw new Error(`beat ${index + 1}: offCamera must be true or false`);
    if (beat.offCamera && index > 0 && !beats[index - 1].offCamera) {
      throw new Error(`beat ${index + 1}: offCamera only on the opening beats, from beat 1 on, since the video can't skip a stretch in the middle`);
    }
    if (beat.offCamera && (beat.say || beat.note || beat.subtitleAt)) {
      throw new Error(`beat ${index + 1}: an off-camera beat is never shown, so it takes no say, note or subtitleAt`);
    }
  }
  if (beats.every(beat => beat.offCamera)) throw new Error('every beat is off camera, so the video would show nothing');
  const labels = project.labels ?? 'page';
  if (!LABELS.includes(labels)) throw new Error(`beats.mjs: labels must be 'page' or 'after', got ${JSON.stringify(labels)}`);
  return labels;
}

// The take's beats with their text from beats.mjs. The beats at the take's positions must still have
// the captions the take recorded, or the text would land on the wrong picture.
async function readProject() {
  if (!fs.existsSync(STEPS)) throw new Error(`no take in ${shown(OUT)}: run record.mjs first`);
  const take = JSON.parse(fs.readFileSync(STEPS, 'utf8'));
  const { steps, trim } = take;
  // A take from before captions has neither key: it started on beat 1 and drew its captions in the page.
  const first = take.first ?? 1;
  const labels = take.labels ?? 'page';
  if (!Array.isArray(steps) || !steps.length) throw new Error(`${shown(STEPS)} lists no beats`);
  if (!Number.isInteger(first) || first < 1) throw new Error(`${shown(STEPS)}: first must be a beat number from 1, got ${plain(JSON.stringify(first))}`);
  if (!LABELS.includes(labels)) throw new Error(`${shown(STEPS)}: labels must be 'page' or 'after', got ${plain(JSON.stringify(labels))}`);
  const times = [trim, ...steps.flatMap(step => [step?.start, step?.end])];
  if (!times.every(Number.isFinite)) throw new Error(`${shown(STEPS)} has a time that isn't a number: run record.mjs again`);
  const project = await import(new URL('./beats.mjs', import.meta.url));
  const wanted = checkBeats(project);
  if (wanted !== labels) {
    console.warn(`warning: beats.mjs says labels '${wanted}', but this take was made with '${labels}', and the captions follow the take: retake to change it`);
  }
  if (take.total !== undefined && project.beats.length !== take.total) {
    throw new Error(`beats.mjs has ${project.beats.length} beats, but this take was made from ${plain(JSON.stringify(take.total))}: beats.mjs changed since the take. Take it again, or put the beats back`);
  }
  const beats = steps.map((step, index) => {
    const number = first + index;
    const beat = project.beats[number - 1];
    // A label drawn only here can be fixed with no retake, once the action shows it's the same beat.
    if (beat?.offCamera) {
      throw new Error(`beat ${number} is off camera in beats.mjs, but this take shows it: take it again, and record.mjs trims it off`);
    }
    const free = labels === 'after' && step.action !== undefined;
    if (!beat || (beat.caption !== step.caption && !free)) {
      const now = beat ? `has the caption "${plain(beat.caption)}"` : 'is gone';
      throw new Error(`beat ${number} ${now} in beats.mjs, but the take recorded "${plain(step.caption)}": beats.mjs changed since the take. Take it again, or put the beat back`);
    }
    // A take from before fingerprints has none, and is checked by its captions alone.
    if (step.action !== undefined && actionPrint(beat.act) !== step.action) {
      throw new Error(`beat ${number}'s action changed in beats.mjs since the take, so its text would land on the wrong picture. Take it again, or put the beat back`);
    }
    return { number, start: step.start - trim, end: step.end - trim, label: beat.caption, say: beat.say ?? '', note: beat.note,
      subtitleAt: beat.subtitleAt ?? 'bottom' };
  });
  return { beats, labels };
}

function lines(beats, labels) {
  console.log(`${shown(STEPS)}: ${beats.length} beats, labels drawn ${labels === 'after' ? 'by captions.mjs' : 'in the page'}\n`);
  let crowded = 0;
  for (const [index, beat] of beats.entries()) {
    const seconds = beat.end - beat.start;
    // voice.mjs counts a clip's beats from 1, so its add takes this number, not the beat's own.
    const part = beat.number === index + 1 ? '' : ` (voice part ${index + 1} of this take)`;
    console.log(`beat ${beat.number}${part}: at ${beat.start.toFixed(1)} s, ${seconds.toFixed(1)} s long`);
    const labelWords = words(beat.label).length;
    const long = labelWords > LABEL_WORDS ? `   (${labelWords} words: keep a label to ${LABEL_WORDS})` : '';
    console.log(`  label: ${plain(beat.label) || '(none)'}${long}`);
    const { count, fit, over } = density(beat.say, seconds);
    if (over) crowded += 1;
    const flag = over ? `   TOO MANY: ${over} over the ${fit} that fit at ${WORDS_PER_SECOND} words a second` : '';
    console.log(`  says:  ${count ? plain(beat.say) : '(nothing)'} (${count} words)${flag}`);
    if (count && beat.subtitleAt === 'top') {
      console.log(`  subtitles at the top${labels === 'after' && labelWords ? ', under the label' : ''}`);
    }
    if (beat.note) console.log(`  note, ${beat.note.at}: ${plain(beat.note.text)}`);
  }
  console.log(crowded
    ? `\n${crowded} of ${beats.length} beats say more than fits: cut words, or give the beat more time in beats.mjs and retake`
    : `\nEvery said line fits its beat at ${WORDS_PER_SECOND} words a second.`);
}

export function srt(beats) {
  const cues = beats.flatMap(beat => subtitleCues(beat.say, beat.start, beat.end));
  // A line reading --> could pass for a timing line in a player's parser.
  return cues.map(({ start, end, lines: rows }, index) => `${index + 1}\n${srtTime(start)} --> ${srtTime(end)}\n${rows.join('\n').replaceAll('-->', '->')}\n`).join('\n');
}

const assTime = seconds => {
  const cs = Math.round(Math.max(0, seconds) * 100);
  const two = value => String(value).padStart(2, '0');
  return `${Math.floor(cs / 360000)}:${two(Math.floor(cs / 6000) % 60)}:${two(Math.floor(cs / 100) % 60)}.${two(cs % 100)}`;
};

// Subtitles bottom centre, or top centre under the label for a beat with subtitleAt 'top', labels top
// centre, notes at their anchors, each on a translucent dark box, sized from the video's height. libass
// moves apart events that would overlap.
export function assScript(beats, labels, width, height) {
  const size = share => Math.max(8, Math.round(height * share));
  const margin = size(0.04);
  const pad = size(0.012);
  // With labels in the page, the page's caption box holds the bottom edge, so subtitles sit above it.
  const subtitleMargin = labels === 'page' ? PAGE_BOX_PX + size(0.015) : margin;
  // A top subtitle clears the label above it: the label's line, then a gap.
  const underLabel = margin + Math.round(size(0.05) * 1.3) + size(0.015);
  const style = (name, fontSize, bold, alignment, marginV) => `Style: ${name},sans-serif,${fontSize},&H00FFFFFF,&H00FFFFFF,`
    + `${BOX},${BOX},${bold},0,0,0,100,100,0,0,3,${pad},0,${alignment},${margin},${margin},${marginV},1`;
  const events = [];
  // Boxes are padded sideways only: each line gets its own box, and a vertical pad would overlap the
  // next line's box in a darker band.
  // A marginV of 0 keeps the style's.
  const event = (start, end, name, text, tags = '', marginV = 0) => events.push(`Dialogue: 0,${assTime(start)},${assTime(end)},${name},,0,0,${marginV},,{\\xbord${pad}\\ybord0${tags}}${text}`);
  for (const beat of beats) {
    const labelled = labels === 'after' && words(beat.label).length > 0;
    const top = beat.subtitleAt === 'top';
    // The label first: libass moves the later of two colliding events, so a label that wraps pushes a top
    // subtitle down rather than landing under it.
    if (labelled) event(beat.start, beat.end, 'Label', assText(beat.label));
    for (const cue of subtitleCues(beat.say, beat.start, beat.end)) {
      event(cue.start, cue.end, top ? 'SubtitleTop' : 'Subtitle', cue.lines.map(assText).join('\\N'), '', top && labelled ? underLabel : 0);
    }
    if (beat.note) event(beat.start, beat.end, 'Note', wrap(beat.note.text, NOTE_CHARS).map(assText).join('\\N'), `\\an${ANCHOR[beat.note.at]}`);
  }
  return [
    '[Script Info]', 'ScriptType: v4.00+', `PlayResX: ${width}`, `PlayResY: ${height}`, 'WrapStyle: 0', 'ScaledBorderAndShadow: yes', '',
    '[V4+ Styles]',
    'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, '
      + 'ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding',
    style('Subtitle', size(0.045), 0, 2, subtitleMargin),
    style('SubtitleTop', size(0.045), 0, 8, margin),
    style('Label', size(0.05), -1, 8, margin),
    style('Note', size(0.035), 0, 5, margin),
    '', '[Events]', 'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text',
    ...events, '',
  ].join('\n');
}

function probe(file) {
  const result = spawnSync('ffprobe', ['-v', 'error', '-show_entries',
    'stream=codec_type,width,height,avg_frame_rate:format=duration', '-of', 'json', file], { encoding: 'utf8' });
  if (result.status !== 0) throw new Error(`can't read ${shown(file)}: ${result.error?.message || result.stderr.trim()}`);
  const { streams = [], format = {} } = JSON.parse(result.stdout);
  return {
    video: streams.find(stream => stream.codec_type === 'video'),
    videos: streams.filter(stream => stream.codec_type === 'video').length,
    audios: streams.filter(stream => stream.codec_type === 'audio').length,
    duration: Number(format.duration) || 0, // An empty file reads N/A.
  };
}

// With no font it can find, libass draws nothing, not even the box, and ffmpeg still exits 0. So draw
// one line on a white frame first and see that it left a mark.
function checkDrawing(dir) {
  const script = path.join(dir, 'probe.ass');
  fs.writeFileSync(script, assScript([{ number: 1, start: 0, end: 2, label: '', say: 'Hg', note: undefined }], 'after', 320, 180));
  const result = spawnSync('ffmpeg', ['-nostdin', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i', 'color=c=white:s=320x180:r=1:d=1',
    '-vf', `ass=filename=${script},signalstats,metadata=print:file=-`, '-frames:v', '1', '-f', 'null', '-'], { encoding: 'utf8' });
  const darkest = Number(/YMIN=(\d+)/.exec(result.stdout ?? '')?.[1] ?? NaN);
  if (result.status !== 0 || !(darkest < DRAWN_BELOW)) {
    throw new Error(`a test line drew nothing, so captions would come out blank: ${result.status === 0 ? 'install a font libass can find (on Debian or Ubuntu, fonts-dejavu-core)' : result.error?.message || result.stderr.trim()}`);
  }
}

function checkFfmpeg() {
  const result = spawnSync('ffmpeg', ['-hide_banner', '-filters'], { encoding: 'utf8' });
  if (result.status !== 0) throw new Error(`ffmpeg won't run: ${result.error?.message || result.stderr.trim()}`);
  if (!/^\s*\S+\s+ass\s/m.test(result.stdout)) {
    throw new Error('this ffmpeg has no ass filter: captions need ffmpeg built with libass (Debian\'s and Ubuntu\'s ffmpeg package have it; on a Mac, Homebrew\'s ffmpeg-full does and its plain ffmpeg doesn\'t)');
  }
}

async function build(beats, labels) {
  checkFfmpeg();
  const source = fs.existsSync(VOICED) ? VOICED : TAKE;
  if (!fs.existsSync(source)) throw new Error(`no take in ${shown(OUT)}: run record.mjs first`);
  const input = probe(source);
  const fps = input.video?.avg_frame_rate;
  if (!input.video || !(rateOf(fps) > 0)) throw new Error(`${shown(source)} has no video with a frame rate in it`);
  // Only this path reaches ffmpeg's filter string. Beat text stays inside the file, where the filter
  // syntax can't read it.
  scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'demo-captions-'));
  const script = path.join(scratch, 'captions.ass');
  if (!SAFE_PATH.test(script)) {
    throw new Error(`the temp dir ${plain(script)} has characters ffmpeg's filter syntax would read: set TMPDIR to a path of only letters, digits, dots, dashes, underscores and slashes`);
  }
  checkDrawing(scratch);
  fs.writeFileSync(script, assScript(beats, labels, input.video.width, input.video.height));
  fs.writeFileSync(SUBTITLES_BUILDING, srt(beats));
  const result = spawnSync('ffmpeg', ['-nostdin', '-y', '-loglevel', 'error', '-i', source, '-vf', `ass=filename=${script}`,
    '-map', '0:v:0', '-map', '0:a?', '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p',
    '-r', fps, '-fps_mode', 'cfr', '-c:a', 'copy', '-movflags', '+faststart', BUILDING], { stdio: ['ignore', 'inherit', 'inherit'] });
  if (result.status !== 0) throw new Error(`ffmpeg failed: ${result.error?.message || 'exit ' + result.status}`);
  const built = probe(BUILDING);
  const frame = 1 / rateOf(fps);
  if (built.videos !== 1 || built.audios !== input.audios || Math.abs(built.duration - input.duration) > frame + 0.001) {
    throw new Error(`the build came out wrong: ${built.videos} video and ${built.audios} audio streams, ${built.duration.toFixed(3)} s, from ${shown(source)} with ${input.audios} audio, ${input.duration.toFixed(3)} s`);
  }
  // spawnSync holds back a signal's handler until ffmpeg ends, so this is where it counts.
  await new Promise(resolve => setImmediate(resolve));
  if (fs.existsSync(RESULT)) fs.copyFileSync(RESULT, PREVIOUS);
  if (fs.existsSync(SUBTITLES)) fs.copyFileSync(SUBTITLES, SUBTITLES_PREVIOUS);
  fs.renameSync(BUILDING, RESULT);
  fs.renameSync(SUBTITLES_BUILDING, SUBTITLES);
  const subtitles = beats.reduce((count, beat) => count + subtitleCues(beat.say, beat.start, beat.end).length, 0);
  const notes = beats.filter(beat => beat.note).length;
  const drawn = labels === 'after' ? `${beats.filter(beat => words(beat.label).length).length} labels` : 'labels in the page already';
  console.log(`${shown(RESULT)}: ${subtitles} subtitles, ${drawn}, ${notes} notes, on ${shown(source)}`);
  if (source === TAKE) console.log('No voice yet, so this is the silent take: after voice.mjs builds demo-voice.mp4, run this again.');
}

// Run as a command, not imported for its functions.
let main = false;
try { main = fs.realpathSync(process.argv[1]) === fs.realpathSync(fileURLToPath(import.meta.url)); } catch { /* no script path: imported */ }
if (main) {
  // The backstop for a failure or a signal: no half-built file left behind.
  process.on('exit', () => {
    fs.rmSync(BUILDING, { force: true });
    fs.rmSync(SUBTITLES_BUILDING, { force: true });
    if (scratch) fs.rmSync(scratch, { recursive: true, force: true });
  });
  for (const [signal, number] of [['SIGINT', 2], ['SIGTERM', 15], ['SIGHUP', 1]]) {
    process.on(signal, () => process.exit(128 + number));
  }
  const [command] = process.argv.slice(2);
  try {
    if (command !== undefined && command !== 'lines') throw new Error(`unknown command "${plain(command)}": use no command, or lines`);
    const { beats, labels } = await readProject();
    if (command === 'lines') lines(beats, labels);
    else await build(beats, labels);
  } catch (e) {
    console.error('captions failed:', e.message);
    if (!command && fs.existsSync(RESULT)) console.error(`this build failed: ${shown(RESULT)} is the last good one, unchanged`);
    process.exitCode = 1;
  }
}
