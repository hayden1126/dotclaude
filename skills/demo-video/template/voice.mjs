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
//   node demo/voice.mjs cues           lists the beats and a line to record each one
//   node demo/voice.mjs check <file>   compares an editor's export with the take
//
// demo/voice/ holds any mix of all.<ext>, one continuous read, and <N>.<ext>, a clip for beat N. A clip
// starts on its beat. Beside a read, it replaces the read across that beat, which is how one part of a
// read gets redone. Silence before the first word is dropped, so a voice lands on its caption however
// late it started.
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
const FILE_NAME = /^(all|\d+)\.[^.]+$/i;
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
const FADE_S = 0.01; // Keeps a cut from clicking.
const SLACK_S = 0.05;
const LENGTH_SLACK_S = 0.1;
const LEAD_IN_S = 3; // Spare time in a recording line, to get ready after pressing Enter.
const RATE_SLACK = 0.1; // An editor's 29.97 is close enough to 30.

const shown = file => path.relative(process.cwd(), file) || '.';
const rateOf = text => { const [top, bottom] = text.split('/').map(Number); return top / (bottom || 1); };

function probe(file) {
  const result = spawnSync('ffprobe', ['-v', 'error', '-show_entries',
    'stream=codec_type,codec_name,width,height,avg_frame_rate:format=duration', '-of', 'json', file], { encoding: 'utf8' });
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
  const peak = windows.reduce((most, window) => Math.max(most, window.Peak_level), -Infinity); // A spread fails past about an hour.
  if (peak < TOO_QUIET_DB) {
    throw new Error(`${shown(file)} is too quiet to be a voice (peak ${peak.toFixed(1)} dB): check the input device, its mute and its level`);
  }
  if (peak >= CLIPPED_DB) console.warn(`warning: ${shown(file)} clipped (peak ${peak.toFixed(1)} dB): turn the input down, or back off the microphone`);
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
  return { from: Math.max(0, first * WINDOW_S - MARGIN_S), to: Math.min(duration, (last + 1) * WINDOW_S + MARGIN_S) };
}

function readTake() {
  if (!fs.existsSync(TAKE) || !fs.existsSync(STEPS)) throw new Error(`no take in ${shown(OUT)}: run record.mjs first`);
  const { steps, trim } = JSON.parse(fs.readFileSync(STEPS, 'utf8'));
  if (!Array.isArray(steps) || !steps.length) throw new Error(`${shown(STEPS)} lists no beats`);
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
    if (!found) throw new Error(`${entry.name}: name it all.<ext> for a whole read, or <beat>.<ext> for one beat`);
    const key = found[1].toLowerCase() === 'all' ? 'all' : Number(found[1]);
    if (key !== 'all' && (key < 1 || key > beats.length)) throw new Error(`${entry.name}: this take has beats 1 to ${beats.length}`);
    if (voices.has(key)) throw new Error(`${entry.name}: ${voices.get(key).name} is already that part, so remove one`);
    voices.set(key, { name: entry.name, file: path.join(dir, entry.name) });
  }
  if (!voices.size) throw new Error(`no voice files in ${shown(dir)}: \`node ${shown(fileURLToPath(import.meta.url))} cues\` lists what to record`);
  for (const voice of voices.values()) Object.assign(voice, speechIn(voice.file));
  return voices;
}

// The stretch of each file to play, and when. Beside a read, a clip stays inside its beat, or it would
// talk over the read coming back.
function placeVoices(voices, beats, length) {
  const read = voices.get('all');
  const opening = beats[0].start;
  const closing = read ? opening + read.to - read.from : 0;
  const clips = [...voices.keys()].filter(key => key !== 'all').sort((one, other) => one - other);
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
    if (stop <= start) continue;
    parts.push({ voice: read, from: read.from + start - opening, to: read.from + stop - opening, at: start });
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
  console.log(`${shown(RESULT)}: ${[...voices.values()].map(voice => voice.name).join(', ')} on ${length.toFixed(1)} s of take`);
}

const quoted = text => (/^[\w@%+=:,./-]+$/.test(text) ? text : `'${text.replaceAll("'", "'\\''")}'`);
const recordLine = (seconds, file) => 'ffmpeg -nostdin -hide_banner -loglevel error -f pulse -i RDPSource '
  + `-t ${Math.ceil(seconds + LEAD_IN_S)} -ac 1 -c:a pcm_s16le -y ${quoted(shown(file))}`;

function cues() {
  const { beats, length } = readTake();
  const dir = voiceDir();
  fs.mkdirSync(dir, { recursive: true });
  console.log(`${shown(TAKE)}: ${length.toFixed(1)} s, ${beats.length} beats\n`);
  beats.forEach(({ caption, start, end }, index) => {
    console.log(`  ${index + 1}. at ${start.toFixed(1)} s, ${(end - start).toFixed(1)} s long: ${caption}`);
  });
  console.log(`\nSave a recording from any app in ${shown(dir)}, as all.<ext> or <beat>.<ext>.`);
  console.log('Under WSLg, the speaker can type one of these. It stops by itself, and spare silence is dropped:\n');
  console.log(`  whole read: ${recordLine(length, path.join(dir, 'all.wav'))}`);
  beats.forEach(({ start, end }, index) => {
    console.log(`  beat ${index + 1}: ${recordLine(end - start, path.join(dir, `${index + 1}.wav`))}`);
  });
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
    if (Math.abs(rate - wantedRate) > RATE_SLACK) problems.push(`frame rate is ${rate.toFixed(2)}, the take is ${wantedRate.toFixed(2)}`);
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
  else if (command === 'check') check(rest[0]);
  else throw new Error(`unknown command "${command}": use no command, cues, or check <file>`);
} catch (e) {
  console.error('voice failed:', e.message);
  if (!command && fs.existsSync(RESULT)) console.error(`this build failed: ${shown(RESULT)} is the last good one, unchanged`);
  process.exitCode = 1;
}
