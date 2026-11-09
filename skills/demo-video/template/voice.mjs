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

// Puts a voice on a finished take. record.mjs makes the silent take; this adds the sound, so a fluffed
// line never costs a new take. It records nothing: any recorder's file works.
//
//   node demo/voice.mjs                builds demo/out/demo-voice.mp4 from the files in demo/voice/
//   node demo/voice.mjs cues           lists each part to record and for how long
//   node demo/voice.mjs add <part> <file>   copies a recording in as all, timed or beat N, checking it first
//   node demo/voice.mjs check <file>   compares an editor's export with the take
//
// demo/voice/ holds any mix of all.<ext>, one continuous read, and <N>.<ext>, a clip for beat N. A clip
// starts on its beat. Beside a read, it replaces the read across that beat, which is how one part of a
// read gets redone. Silence before the first word is dropped, so a voice lands on its caption however
// late it started. timed.<ext> takes the place of all.<ext> for a read already lined up with the take,
// such as an editor's export recorded over it as it played: it keeps its own timing from the take's
// first frame.
//
// Env: OUT is the take's dir, by default out/ beside this file. VOICE is the voice files' dir, by
// default named after OUT (out/ pairs with voice/, out-clip/ with voice-clip/), since a beat number
// means a beat of one take.
//
// A build fails loud, and a failed one leaves the last good file alone. A good one moves the file it
// replaces to demo-voice.prev.mp4. The picture is copied, never re-encoded.
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.resolve(process.env.OUT || path.join(HERE, 'out'));
const TAKE = path.join(OUT, 'demo.mp4');
const STEPS = path.join(OUT, 'steps.json');
const RESULT = path.join(OUT, 'demo-voice.mp4');
const PREVIOUS = path.join(OUT, 'demo-voice.prev.mp4');
const BUILDING = path.join(OUT, `.demo-voice.${process.pid}.mp4`);
const CAPTIONED = path.join(OUT, 'demo-captioned.mp4');
const CAPTIONED_PREVIOUS = path.join(OUT, 'demo-captioned.prev.mp4');
const FILE_NAME = /^(all|timed|\d+)\.[^.]+$/i;
const READS = ['all', 'timed']; // A whole read: at most one of these, beside any clips.
const keyOf = name => (READS.includes(name.toLowerCase()) ? name.toLowerCase() : Number(name)); // 02.wav is beat 2.
const TOO_QUIET_DB = -25; // A real microphone gave -31 dB on a room with nobody talking, and 0 dB on a voice.
const CLIPPED_DB = -0.1;
const RATE = 48000;
const WINDOW_S = 0.05; // Speech is found in windows this long.
const ABOVE_FLOOR_DB = 10; // Speech is this much louder than the room's own noise, or half the way to the loudest,
const BELOW_LOUDEST_DB = 35; // and no quieter than this under the loudest window, in a silent room.
const SOFT_ABOVE_FLOOR_DB = 4; // A soft sound joined to speech, such as a breathy opening, only clears these.
const SOFT_BELOW_LOUDEST_DB = 50;
const ALL_SPEECH_DB = 6; // A file whose windows span less than this has no quiet part: it is all speech.
const THIN_DB = 16; // A voice less than this over the room's noise is found, but only roughly.
const RUN = 3; // Loud windows in a row that start or end the speech: a short word fills 3, a click under 0.05 s at most 2.
const MARGIN_S = 0.1; // Kept around the speech.
const SIDECAR = /:Zone\.Identifier$/; // Windows writes one beside a downloaded file copied to a Linux disk.
const PARTS = '.parts.json'; // What each added part was recorded for, so a later take can't silently reuse it.
const MOVED_S = 0.5; // A part whose beat moved or changed length more than this no longer fits.
const FADE_S = 0.01; // Keeps a cut from clicking.
const SLACK_S = 0.05;
const LENGTH_SLACK_S = 0.1;
const LEAD_IN_S = 3; // Spare time in a recording line, to get ready after pressing Enter.
const LONG_LINE_S = 110; // A recording line typed at Claude Code's prompt may be stopped at 2 minutes.
const CUT_OFF_S = 0.15; // Speech this close to a file's end may have been cut off.
const RATE_SLACK = 0.1; // An editor's 29.97 is close enough to 30.

const shown = file => path.relative(process.cwd(), file) || '.';
const rateOf = text => { const [top, bottom] = text.split('/').map(Number); return top / (bottom || 1); };

function probe(file) {
  const result = spawnSync('ffprobe', ['-v', 'error', '-show_entries',
    'stream=codec_type,codec_name,width,height,avg_frame_rate,start_time:format=duration', '-of', 'json', file], { encoding: 'utf8' });
  if (result.status !== 0) throw new Error(`can't read ${shown(file)}: ${result.error?.message || result.stderr.trim()}`);
  const { streams = [], format = {} } = JSON.parse(result.stdout);
  return {
    video: streams.find(stream => stream.codec_type === 'video'),
    audio: streams.find(stream => stream.codec_type === 'audio'),
    videos: streams.filter(stream => stream.codec_type === 'video').length,
    audios: streams.filter(stream => stream.codec_type === 'audio').length,
    duration: Number(format.duration) || 0, // An empty file reads N/A.
  };
}

// Where a file's sound starts on its own clock, from its picture's start when it has one. Lengths and
// speech come from counting decoded samples, which start at 0, so a timed read adds this back: an
// export whose audio track starts late would otherwise play early by that much.
function soundStartOf(file) {
  const { audio, video } = probe(file);
  const sound = Number(audio?.start_time);
  const picture = Number(video?.start_time);
  return Number.isFinite(sound) ? sound - (Number.isFinite(picture) ? picture : 0) : 0;
}

function analyse(file, filter) {
  const result = spawnSync('ffmpeg', ['-nostdin', '-nostats', '-hide_banner', '-i', file, '-map', '0:a:0', '-af', filter,
    '-f', 'null', '-'], { encoding: 'utf8' });
  if (result.status !== 0) throw new Error(`can't read ${shown(file)}: ${result.error?.message || result.stderr.trim()}`);
  return result.stderr;
}

function peakOf(file) {
  const found = /max_volume: (-?[\d.]+) dB/.exec(analyse(file, 'volumedetect'));
  return found ? Number(found[1]) : -Infinity; // Pure digital silence prints no number.
}

// A container may not know its own length (a piped webm reads N/A), so lengths and levels come from
// the decoded sound, one window at a time.
function windowsOf(file) {
  const result = spawnSync('ffmpeg', ['-nostdin', '-nostats', '-hide_banner', '-loglevel', 'error', '-i', file, '-map', '0:a:0',
    '-af', `aformat=sample_rates=${RATE}:channel_layouts=mono,asetnsamples=n=${RATE * WINDOW_S}:p=0,`
      + 'astats=metadata=1:reset=1:measure_perchannel=none:measure_overall=Peak_level+RMS_level+Number_of_samples,'
      + 'ametadata=mode=print:file=-', '-f', 'null', '-'], { encoding: 'utf8', maxBuffer: 1 << 28 });
  if (result.status !== 0) throw new Error(`can't read ${shown(file)}: ${result.error?.message || result.stderr.trim()}`);
  const windows = [];
  for (const line of result.stdout.split('\n')) {
    if (line.startsWith('frame:')) windows.push({ Peak_level: -Infinity, RMS_level: -Infinity, Number_of_samples: 0 });
    const found = /^lavfi\.astats\.Overall\.(\w+)=(.+)$/.exec(line.trim());
    if (found && windows.length) {
      const value = Number(found[2]);
      windows.at(-1)[found[1]] = Number.isNaN(value) ? -Infinity : value; // Silence reads -inf.
    }
  }
  return windows;
}

// Where the speech in a file starts and stops. The bar sits over the room's own noise, so a noisy
// room still trims, and a click before the first word is too short to start the speech.
function speechIn(file) {
  const windows = windowsOf(file);
  const duration = windows.reduce((sum, window) => sum + window.Number_of_samples, 0) / RATE;
  if (!duration) throw new Error(`${shown(file)} has no audio in it`);
  if (!windows.some(window => window.Peak_level >= TOO_QUIET_DB)) {
    throw new Error(`${shown(file)} is too quiet to be a voice: check the input device, its mute and its level`);
  }
  const levels = windows.map(window => window.RMS_level);
  // The room's noise, from windows with any sound in them: a recorder's opening zeros (-inf) aren't the room.
  const heard = levels.filter(Number.isFinite).sort((one, other) => one - other);
  const loudest = heard.at(-1);
  const floor = heard[Math.floor(heard.length / 10)];
  const range = loudest - floor;
  const allSpeech = range < ALL_SPEECH_DB;
  if (!allSpeech && range < THIN_DB) {
    console.warn(`warning: ${shown(file)}: the voice is only ${range.toFixed(0)} dB over the room's noise, so where it starts and ends is rough: listen to the result`);
  }
  const bar = allSpeech ? loudest - BELOW_LOUDEST_DB
    : Math.max(floor + Math.min(ABOVE_FLOOR_DB, range / 2), loudest - BELOW_LOUDEST_DB);
  const softBar = allSpeech ? loudest - SOFT_BELOW_LOUDEST_DB
    : Math.max(floor + Math.min(SOFT_ABOVE_FLOOR_DB, range / 4), loudest - SOFT_BELOW_LOUDEST_DB);
  const loud = levels.map(level => level > bar);
  const run = index => index >= 0 && index + RUN <= loud.length && loud.slice(index, index + RUN).every(Boolean);
  let first = loud.findIndex((_, index) => run(index));
  if (first < 0) throw new Error(`${shown(file)} has no stretch of speech in it, only short sounds`);
  let last = loud.length - 1;
  while (!run(last - RUN + 1)) last -= 1;
  // Grow outwards over soft sound joined to the speech, which the bar alone would cut.
  while (first > 0 && levels[first - 1] > softBar) first -= 1;
  while (last < levels.length - 1 && levels[last + 1] > softBar) last += 1;
  // Judged on the speech kept, so a loud click that's trimmed off can't pass a voice that's too quiet.
  const peak = windows.slice(first, last + 1).reduce((most, window) => Math.max(most, window.Peak_level), -Infinity);
  if (peak < TOO_QUIET_DB) {
    throw new Error(`${shown(file)} is too quiet to be a voice (peak ${peak.toFixed(1)} dB): check the input device, its mute and its level`);
  }
  if (peak >= CLIPPED_DB) console.warn(`warning: ${shown(file)} clipped (peak ${peak.toFixed(1)} dB): turn the input down, or back off the microphone`);
  if ((last + 1) * WINDOW_S >= duration - CUT_OFF_S) {
    console.warn(`warning: ${shown(file)} ends while the voice is still going: if the recording was cut off, record it again`);
  }
  return { from: Math.max(0, first * WINDOW_S - MARGIN_S), to: Math.min(duration, (last + 1) * WINDOW_S + MARGIN_S), duration };
}

function readTake() {
  if (!fs.existsSync(TAKE) || !fs.existsSync(STEPS)) throw new Error(`no take in ${shown(OUT)}: run record.mjs first`);
  const { steps, trim } = JSON.parse(fs.readFileSync(STEPS, 'utf8'));
  if (!Array.isArray(steps) || !steps.length) throw new Error(`${shown(STEPS)} lists no beats`);
  const times = [trim, ...steps.flatMap(step => [step?.start, step?.end])];
  if (!times.every(Number.isFinite)) throw new Error(`${shown(STEPS)} has a time that isn't a number: run record.mjs again`);
  // steps.json counts from before the trim, as captions.srt doesn't.
  const beats = steps.map(({ caption, start, end }) => ({ caption, start: start - trim, end: end - trim }));
  return { beats, length: probe(TAKE).duration };
}

function voiceDir() {
  if (process.env.VOICE) return path.resolve(process.env.VOICE);
  const name = path.basename(OUT);
  if (!/^out(?:$|[-_.\d])/.test(name)) throw new Error(`OUT is ${shown(OUT)}, so set VOICE too: only an OUT named out... has a voice dir of its own`);
  return path.join(path.dirname(OUT), 'voice' + name.slice('out'.length));
}

// What a part was recorded for: a clip, its beat's caption and length; a read, every caption and start.
function fitFor(key, beats) {
  if (READS.includes(key)) return { captions: beats.map(beat => beat.caption), starts: beats.map(beat => beat.start) };
  const { caption, start, end } = beats[key - 1];
  return { caption, length: end - start };
}

function misfit(key, was, beats) {
  const now = fitFor(key, beats);
  if (READS.includes(key)) {
    if (JSON.stringify(was.captions) !== JSON.stringify(now.captions)) return 'the beats changed';
    const moved = Math.max(...now.starts.map((start, index) => Math.abs(start - was.starts[index])));
    return moved > MOVED_S ? `a beat moved ${moved.toFixed(1)} s` : null;
  }
  if (was.caption !== now.caption) return `beat ${key}'s caption changed`;
  const change = now.length - was.length;
  return Math.abs(change) > MOVED_S ? `beat ${key} is ${Math.abs(change).toFixed(1)} s ${change > 0 ? 'longer' : 'shorter'}` : null;
}

function readFits(dir) {
  try { return JSON.parse(fs.readFileSync(path.join(dir, PARTS), 'utf8')); } catch { return {}; }
}

function readVoices(beats) {
  const dir = voiceDir();
  const names = fs.existsSync(dir) ? fs.readdirSync(dir, { withFileTypes: true }) : [];
  const voices = new Map();
  for (const entry of names) {
    if (entry.name.startsWith('.') || SIDECAR.test(entry.name)) continue;
    const stat = fs.statSync(path.join(dir, entry.name), { throwIfNoEntry: false }); // Follows a symlink.
    if (!stat) throw new Error(`${entry.name} is a link to nothing`);
    if (stat.isDirectory()) continue;
    if (!stat.isFile()) throw new Error(`${entry.name} is not a file`);
    const found = FILE_NAME.exec(entry.name);
    if (!found) throw new Error(`${entry.name}: name it all.<ext> for a whole read, timed.<ext> for one timed in an editor, or <beat>.<ext> for one beat`);
    const key = keyOf(found[1]);
    if (!READS.includes(key) && (key < 1 || key > beats.length)) throw new Error(`${entry.name}: this take has beats 1 to ${beats.length}`);
    if (voices.has(key)) throw new Error(`${entry.name}: ${voices.get(key).name} is already that part, so remove one`);
    voices.set(key, { name: entry.name, file: path.join(dir, entry.name) });
  }
  if (voices.has('all') && voices.has('timed')) {
    throw new Error(`${voices.get('all').name} and ${voices.get('timed').name} are both a whole read, so remove one`);
  }
  if (!voices.size) throw new Error(`no voice files in ${shown(dir)}: \`node ${shown(fileURLToPath(import.meta.url))} cues\` lists what to record`);
  const fits = readFits(dir);
  const stale = [];
  for (const [key, voice] of voices) {
    if (!fits[key]) console.warn(`warning: ${voice.name} wasn't added with add, so nothing says which take it was recorded for: listen`);
    else if (misfit(key, fits[key], beats)) stale.push(`${voice.name} (${misfit(key, fits[key], beats)})`);
  }
  if (stale.length) {
    throw new Error(`recorded for an earlier take: ${stale.join(', ')}. Record them again, or add the same file again to keep it as it is`);
  }
  for (const voice of voices.values()) Object.assign(voice, speechIn(voice.file));
  if (voices.has('timed')) voices.get('timed').soundStart = soundStartOf(voices.get('timed').file);
  return voices;
}

// The stretch of each file to play, and when. Beside a read, a clip stays inside its beat, or it would
// talk over the read coming back.
function placeVoices(voices, beats, length) {
  const read = voices.get('all') ?? voices.get('timed');
  // How far the read moves: a read's first word onto the first caption, a timed read to where its sound
  // starts on its own clock.
  const shift = !read ? 0 : voices.has('timed') ? read.soundStart : beats[0].start - read.from;
  // A timed read's sound can start a few ms before its picture (Opus in Matroska reads -0.007 s); the take
  // starts at 0, so the read does too.
  const opening = read ? Math.max(0, read.from + shift) : 0;
  const closing = read ? read.to + shift : 0;
  const clips = [...voices.keys()].filter(key => !READS.includes(key)).sort((one, other) => one - other);
  const parts = clips.map((beat, index) => {
    const clip = voices.get(beat);
    const { start, end } = beats[beat - 1];
    const next = clips[index + 1];
    const [limit, what] = read && closing > end ? [end, 'the read comes back']
      : next ? [beats[next - 1].start, `beat ${next}'s clip`] : [length, 'the take ends'];
    const spoken = clip.to - clip.from;
    if (start + spoken > limit + SLACK_S) {
      throw new Error(`${clip.name} runs ${spoken.toFixed(1)} s, and beat ${beat} has ${(limit - start).toFixed(1)} s before ${what}: shorten it, or give the beat more time`);
    }
    return { voice: clip, from: clip.from, to: clip.to, at: start };
  });
  if (!read) return parts;

  const spans = [];
  let at = opening;
  for (const beat of clips) {
    const { start, end } = beats[beat - 1];
    if (start > at) spans.push([at, start]);
    at = Math.max(at, end);
  }
  if (closing > at) spans.push([at, closing]);
  for (const [start, end] of spans) {
    const stop = Math.min(end, closing);
    // Beats can sit a millisecond apart, which would let a tick of the read play between two clips.
    if (stop - start < 2 * FADE_S) continue;
    parts.push({ voice: read, from: start - shift, to: stop - shift, at: start });
  }
  const last = Math.max(...parts.map(part => part.at + part.to - part.from));
  if (last > length + SLACK_S) {
    throw new Error(`${read.name} runs ${(last - length).toFixed(1)} s past the end of the take: read faster, or give the beats more time`);
  }
  return parts;
}

function mux(parts, length) {
  const files = [...new Set(parts.map(part => part.voice.file))];
  const graph = parts.map(({ voice, from, to, at }, index) => {
    const spoken = to - from;
    // Timed from the samples, as speechIn measured them, so a file whose clock starts late or skips
    // still trims where its speech is.
    return `[${files.indexOf(voice.file) + 1}:a]aformat=sample_rates=${RATE}:channel_layouts=mono,asetpts=N/SR/TB,`
      + `atrim=start=${from}:end=${to},asetpts=PTS-STARTPTS,`
      + `afade=t=in:d=${FADE_S},afade=t=out:st=${Math.max(0, spoken - FADE_S)}:d=${FADE_S},`
      // After a trim, adelay hands amix times that leave a stream 8 ms long, far past the end of
      // the file (ffmpeg 6.1). Counting them again from the samples keeps every part on its time.
      + `adelay=${Math.round(at * 1000)}:all=1,asetpts=N/SR/TB[part${index}]`;
  });
  const mixed = parts.map((_, index) => `[part${index}]`).join('');
  graph.push(`${mixed}amix=inputs=${parts.length}:normalize=0:duration=longest,apad[voice]`);
  // Not -shortest: a voice that ends early would cut the picture off with it. The padding and -t give
  // the sound exactly the take's length.
  const result = spawnSync('ffmpeg', ['-nostdin', '-y', '-loglevel', 'error', '-i', TAKE, ...files.flatMap(file => ['-i', file]),
    '-filter_complex', graph.join(';'), '-map', '0:v:0', '-map', '[voice]', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
    '-t', String(length), '-movflags', '+faststart', BUILDING], { stdio: ['ignore', 'inherit', 'inherit'] });
  if (result.status !== 0) throw new Error(`ffmpeg failed: ${result.error?.message || 'exit ' + result.status}`);
  const built = probe(BUILDING);
  if (built.videos !== 1 || built.audios !== 1 || Math.abs(built.duration - length) > LENGTH_SLACK_S) {
    throw new Error(`the build came out wrong: ${built.videos} video and ${built.audios} audio streams, ${built.duration.toFixed(2)} s for a ${length.toFixed(2)} s take`);
  }
  // Streams of the right shape can still hold nothing, and only this catches a silent build.
  const peak = peakOf(BUILDING);
  if (peak < TOO_QUIET_DB) throw new Error(`the build came out silent (peak ${peak} dB) though its voice files are not`);
}

async function build() {
  const { beats, length } = readTake();
  const voices = readVoices(beats);
  const parts = placeVoices(voices, beats, length);
  mux(parts, length);
  // spawnSync holds back a signal's handler until ffmpeg ends, so this is where it counts.
  await new Promise(resolve => setImmediate(resolve));
  if (fs.existsSync(RESULT)) fs.copyFileSync(RESULT, PREVIOUS);
  fs.renameSync(BUILDING, RESULT);
  // Captions were burned into the old voice, so that file no longer matches this one.
  if (fs.existsSync(CAPTIONED)) {
    fs.renameSync(CAPTIONED, CAPTIONED_PREVIOUS);
    console.warn('this build replaced the voice demo-captioned.mp4 was made from: moved it to demo-captioned.prev.mp4. Run captions.mjs again');
  }
  console.log(`${shown(RESULT)}: ${[...voices.values()].map(voice => voice.name).join(', ')} on ${length.toFixed(1)} s of take`);
}

// The app writes steps.json, so a caption is printed with no control, line-separator or direction
// characters: it can't move the cursor, clear a line, reorder text or start a line that passes for
// something else.
const plain = text => String(text).replace(/[\u0000-\u001f\u007f-\u009f\u200e\u200f\u2028\u2029\u202a-\u202e\u2066-\u2069]+/g, ' ');

// Prints no shell command. The person speaking runs the recording line outside the sandbox, and this
// file sits in the project, where the sandboxed session or the app could change it, so the line lives
// in the skill's own SKILL.md; only the part and the seconds below go into it.
function cues() {
  const { beats, length } = readTake();
  console.log(`${shown(TAKE)}: ${length.toFixed(1)} s, ${beats.length} beats\n`);
  const part = (name, seconds, what) => {
    const record = Math.ceil(seconds + LEAD_IN_S);
    console.log(`  part ${name}: record ${record} s. ${what}`);
    if (record > LONG_LINE_S) console.log('    (over 2 minutes: run its line in your own terminal, since a ! line may be stopped at 2 minutes)');
  };
  part('all', length, 'The whole read.');
  console.log('  part timed: the whole read, recorded over the take in an editor as it played, from its first frame. It keeps its timing.');
  beats.forEach(({ caption, start, end }, index) => {
    part(String(index + 1), end - start, `At ${start.toFixed(1)} s, ${(end - start).toFixed(1)} s long: ${plain(caption)}`);
  });
  console.log('\nRecord each part with any app, or with the recording line in the demo-video skill, then give the file\'s path to Claude to add.');
}

// Copies a recording in, from inside the sandbox, so a link in the voice dir can only redirect a write
// the sandbox allows anyway. The part's last file stays beside it, hidden, until the next add.
function add(part, file) {
  if (!part || !file) throw new Error('add needs a part and a file: node demo/voice.mjs add <all, timed or beat> <file>');
  const { beats, length } = readTake();
  const key = READS.includes(part.toLowerCase()) || /^\d+$/.test(part) ? keyOf(part) : null;
  if (key === null || (!READS.includes(key) && (key < 1 || key > beats.length))) {
    throw new Error(`part is all, timed, or a beat from 1 to ${beats.length}, not "${part}"`);
  }
  const extension = path.extname(file).toLowerCase() || '.audio'; // ffmpeg reads a file by its content.
  // Refuses a silent file now, not at the build. The length is the decoded sound's, since a container
  // may not know its own.
  const { duration } = speechIn(path.resolve(file));
  // For a timed read, the export's own length when its container knows it, since an editor's sound may
  // stop where the recording does. Otherwise the decoded sound, from where it starts.
  const runs = key === 'timed' ? probe(path.resolve(file)).duration || soundStartOf(path.resolve(file)) + duration : duration;
  if (key === 'timed' && Math.abs(runs - length) > MOVED_S) {
    console.warn(`warning: ${plain(file)} runs ${runs.toFixed(1)} s and the take is ${length.toFixed(1)} s. A timed read keeps its place from the file's first second, so it must be an export of the whole take, started at 0: if the editor's timeline was trimmed or shifted, the voice is off by that much`);
  }
  const sound = fs.readFileSync(file); // Read first: the file may be the one about to move aside.
  const dir = voiceDir();
  fs.mkdirSync(dir, { recursive: true });
  for (const entry of fs.readdirSync(dir)) {
    const found = FILE_NAME.exec(entry);
    // A new whole read replaces the last one of either kind, since a build takes only one.
    const same = found && (READS.includes(key) ? READS.includes(keyOf(found[1])) : keyOf(found[1]) === key);
    if (same) fs.renameSync(path.join(dir, entry), path.join(dir, `.${entry}.prev`));
  }
  const target = path.join(dir, `${key}${extension}`);
  fs.writeFileSync(target, sound);
  const fits = readFits(dir);
  fits[key] = fitFor(key, beats);
  fs.writeFileSync(path.join(dir, PARTS), JSON.stringify(fits, null, 1));
  console.log(`${shown(target)}: added, from ${file}`);
}

function check(file) {
  if (!file) throw new Error('check needs a file: node demo/voice.mjs check <file>');
  const take = probe(TAKE);
  const edit = probe(file);
  const problems = [];
  if (!edit.video) {
    problems.push('no video');
  } else {
    const size = `${edit.video.width}x${edit.video.height}`;
    const wanted = `${take.video.width}x${take.video.height}`;
    if (size !== wanted) problems.push(`size is ${size}, the take is ${wanted}`);
    const rate = rateOf(edit.video.avg_frame_rate);
    const wantedRate = rateOf(take.video.avg_frame_rate);
    if (!(Math.abs(rate - wantedRate) <= RATE_SLACK)) problems.push(`frame rate is ${rate.toFixed(2)}, the take is ${wantedRate.toFixed(2)}`);
    if (edit.video.codec_name !== take.video.codec_name) problems.push(`video is ${edit.video.codec_name}, the take is ${take.video.codec_name}`);
  }
  if (!edit.audio) problems.push('no audio');
  else if (peakOf(file) < TOO_QUIET_DB) problems.push('the audio is close to silent');
  if (problems.length) throw new Error(`${shown(file)}: ${problems.join('; ')}`);
  const gap = edit.duration - take.duration;
  const change = Math.abs(gap) <= LENGTH_SLACK_S ? 'the same length as' : `${Math.abs(gap).toFixed(1)} s ${gap < 0 ? 'shorter' : 'longer'} than`;
  console.log(`${shown(file)}: format matches, ${edit.duration.toFixed(1)} s, ${change} the take. Check that against the event's limit.`);
}

// The backstop for a failure or a signal: no half-built file left behind.
process.on('exit', () => fs.rmSync(BUILDING, { force: true }));
for (const [signal, number] of [['SIGINT', 2], ['SIGTERM', 15], ['SIGHUP', 1]]) {
  process.on(signal, () => process.exit(128 + number));
}

const [command, ...rest] = process.argv.slice(2);
try {
  if (!command) await build();
  else if (command === 'cues') cues();
  else if (command === 'add') add(rest[0], rest[1]);
  else if (command === 'check') check(rest[0]);
  else throw new Error(`unknown command "${command}": use no command, cues, add <part> <file>, or check <file>`);
} catch (e) {
  console.error('voice failed:', e.message);
  if (!command && fs.existsSync(RESULT)) console.error(`this build failed: ${shown(RESULT)} is the last good one, unchanged`);
  process.exitCode = 1;
}
