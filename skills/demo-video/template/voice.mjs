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
// Env: OUT is the take's dir and VOICE the files' dir, by default out/ and voice/ beside this file.
//
// A build fails loud, and a failed one leaves the last good file alone. A good one moves the file it
// replaces to demo-voice.prev.mp4. The picture is copied, never re-encoded.
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.resolve(process.env.OUT || path.join(HERE, 'out'));
const VOICE = path.resolve(process.env.VOICE || path.join(HERE, 'voice'));
const TAKE = path.join(OUT, 'demo.mp4');
const STEPS = path.join(OUT, 'steps.json');
const RESULT = path.join(OUT, 'demo-voice.mp4');
const PREVIOUS = path.join(OUT, 'demo-voice.prev.mp4');
const BUILDING = path.join(OUT, `.demo-voice.${process.pid}.mp4`);
const FILE_NAME = /^(all|\d+)\.[^.]+$/i;
const TOO_QUIET_DB = -25; // A real microphone gave -31 dB on a room with nobody talking, and 0 dB on a voice.
const CLIPPED_DB = -0.1;
const BELOW_PEAK_DB = 25; // Quieter than this under the file's own peak isn't speech, so a key click before it isn't either.
const PAUSE_S = 0.2; // Silence shorter than this is a gap between words.
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

// Where the speech in a file starts and stops, by the file's own peak, so a quiet recorder works too.
function speechIn(file, duration) {
  const peak = peakOf(file);
  if (peak < TOO_QUIET_DB) {
    throw new Error(`${shown(file)} is too quiet to be a voice (peak ${peak} dB): check the input device, its mute and its level`);
  }
  if (peak >= CLIPPED_DB) console.warn(`warning: ${shown(file)} clipped (peak ${peak} dB): turn the input down, or back off the microphone`);
  const log = analyse(file, `silencedetect=n=${peak - BELOW_PEAK_DB}dB:d=${PAUSE_S}`);
  const starts = [...log.matchAll(/silence_start: (-?[\d.]+)/g)].map(match => Number(match[1]));
  const ends = [...log.matchAll(/silence_end: (-?[\d.]+)/g)].map(match => Number(match[1]));
  const from = starts.length && starts[0] <= SLACK_S && ends.length ? ends[0] : 0;
  const trailing = starts.length > ends.length || ends.at(-1) >= duration - SLACK_S;
  const to = starts.length && trailing && starts.at(-1) > from ? starts.at(-1) : duration;
  return { from, to };
}

function readTake() {
  if (!fs.existsSync(TAKE) || !fs.existsSync(STEPS)) throw new Error(`no take in ${shown(OUT)}: run record.mjs first`);
  const { steps, trim } = JSON.parse(fs.readFileSync(STEPS, 'utf8'));
  if (!Array.isArray(steps) || !steps.length) throw new Error(`${shown(STEPS)} lists no beats`);
  // steps.json counts from before the trim, as captions.srt doesn't.
  const beats = steps.map(({ caption, start, end }) => ({ caption, start: start - trim, end: end - trim }));
  return { beats, length: probe(TAKE).duration };
}

function readVoices(beats) {
  const names = fs.existsSync(VOICE) ? fs.readdirSync(VOICE, { withFileTypes: true }) : [];
  const voices = new Map();
  for (const entry of names) {
    if (!entry.isFile() || entry.name.startsWith('.')) continue;
    const found = FILE_NAME.exec(entry.name);
    if (!found) throw new Error(`${entry.name}: name it all.<ext> for a whole read, or <beat>.<ext> for one beat`);
    const key = found[1].toLowerCase() === 'all' ? 'all' : Number(found[1]);
    if (key !== 'all' && (key < 1 || key > beats.length)) throw new Error(`${entry.name}: this take has beats 1 to ${beats.length}`);
    if (voices.has(key)) throw new Error(`${entry.name}: ${voices.get(key).name} is already that part, so remove one`);
    voices.set(key, { name: entry.name, file: path.join(VOICE, entry.name) });
  }
  if (!voices.size) throw new Error(`no voice files in ${shown(VOICE)}: \`node ${shown(fileURLToPath(import.meta.url))} cues\` lists what to record`);
  for (const voice of voices.values()) {
    const { audio, duration } = probe(voice.file);
    if (!audio) throw new Error(`${voice.name} has no audio in it`);
    Object.assign(voice, speechIn(voice.file, duration));
  }
  return voices;
}

// The stretch of each file to play, and when. Beside a read, a clip stays inside its beat, or it would
// talk over the read coming back.
function placeVoices(voices, beats, length) {
  const read = voices.get('all');
  const clips = [...voices.keys()].filter(key => key !== 'all').sort((one, other) => one - other);
  const parts = clips.map((beat, index) => {
    const clip = voices.get(beat);
    const { start, end } = beats[beat - 1];
    const next = clips[index + 1];
    const [limit, what] = read ? [end, 'the read comes back']
      : next ? [beats[next - 1].start, `beat ${next}'s clip`] : [length, 'the take ends'];
    const spoken = clip.to - clip.from;
    if (start + spoken > limit + SLACK_S) {
      throw new Error(`${clip.name} runs ${spoken.toFixed(1)} s, and beat ${beat} has ${(limit - start).toFixed(1)} s before ${what}: shorten it, or give the beat more time`);
    }
    return { voice: clip, from: clip.from, to: clip.to, at: start };
  });
  if (!read) return parts;

  const opening = beats[0].start;
  const spans = [];
  let at = opening;
  for (const beat of clips) {
    const { start, end } = beats[beat - 1];
    if (start > at) spans.push([at, start]);
    at = Math.max(at, end);
  }
  const closing = opening + read.to - read.from;
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
    return `[${files.indexOf(voice.file) + 1}:a]atrim=start=${from}:end=${to},asetpts=PTS-STARTPTS,`
      + 'aformat=sample_rates=48000:channel_layouts=mono,'
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
  fs.mkdirSync(VOICE, { recursive: true });
  console.log(`${shown(TAKE)}: ${length.toFixed(1)} s, ${beats.length} beats\n`);
  beats.forEach(({ caption, start, end }, index) => {
    console.log(`  ${index + 1}. at ${start.toFixed(1)} s, ${(end - start).toFixed(1)} s long: ${caption}`);
  });
  console.log(`\nSave a recording from any app in ${shown(VOICE)}, as all.<ext> or <beat>.<ext>.`);
  console.log('Under WSLg, the speaker can type one of these. It stops by itself, and spare silence is dropped:\n');
  console.log(`  whole read: ${recordLine(length, path.join(VOICE, 'all.wav'))}`);
  beats.forEach(({ start, end }, index) => {
    console.log(`  beat ${index + 1}: ${recordLine(end - start, path.join(VOICE, `${index + 1}.wav`))}`);
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
