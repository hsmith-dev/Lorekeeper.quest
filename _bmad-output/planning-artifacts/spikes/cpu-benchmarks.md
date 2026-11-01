# Spike: CPU benchmarks for STT, TTS and NLI

Date: 2026-10-31. Covers Story 0 in `research-decisions-summary.md` (cross-cutting decision 3). Time-boxed to about 45 minutes. Each configuration was run once (n=1) after one warm-up call. The variance between runs is large. Re-running to check the appendix scripts gave faster-whisper base float32 a full-clip time of 11.8 s against 6.9 s the first time, about 2.0 s against 1.5 s per 15 s chunk. Kokoro RTF ranged from 0.25 to 0.38 across runs. Treat any timing as accurate only to within about ±50%.

## 1. Machine and constraints

| Item | Value |
|---|---|
| CPU | Apple M5 Max, 18 cores (`sysctl -n machdep.cpu.brand_string hw.ncpu`) |
| RAM | 48 GB (`hw.memsize` = 51539607552) |
| OS | macOS 27.2 (26B123), arm64 |
| Python | 3.12.14 in isolated `uv venv`s (uv 0.12.19) |
| Thread cap | `OMP_NUM_THREADS=4`, plus `cpu_threads=4` (CTranslate2) or `torch.set_num_threads(4)` |
| Libraries | faster-whisper 1.2.1 / ctranslate2 4.8.4; openai-whisper 20250625; torch 2.15.0; sentence-transformers 6.2.0 / transformers 5.22.1; kokoro 0.9.4 / misaki 0.9.4 / spaCy 3.8.18 |
| Peak RSS | `/usr/bin/time -l` "maximum resident set size" for the whole process, including the Python, torch and tokenizer runtime |

**Read these as an optimistic upper bound for the target box (about 8 GB RAM, CPU-only, probably x86).** A 4-thread cap does not remove the M5's per-core speed, large caches or memory bandwidth. The target box is likely to be 2–5× slower. There is one exception: CTranslate2 **int8 on arm64 is unusually slow** (see §3.1). Its float32 path probably runs through Apple Accelerate/AMX, and int8 does not. That makes the int8 numbers here *pessimistic* compared with an x86 CPU that has AVX2/VNNI. The 4× speed-up the research credits to faster-whisper int8 cannot be confirmed or ruled out on this machine. The peak-RSS figures carry over to the target much better than the timings do.

## 2. Results

Test audio: 67.1 s of TTRPG table talk (GM narration, dice rolls, the names Karak Dun, Borin Stonebeard, Grukk, Aldric, Veyra and Dawnbreaker). It was synthesised with macOS `say` and converted to 16 kHz mono PCM16, then split into 4 × 15 s chunks plus one 7.1 s tail. Audio goes in as a numpy array, which is also how a live WebSocket PCM path would feed it. "Word match" is the share of script words recovered in order (difflib), a rough accuracy proxy and not a real WER. Every STT run uses `beam_size=5`, `language="en"` and no VAD.

### 2.1 Speech-to-text

| Model | Full 67 s clip | Full RTF | 15 s chunk mean / worst | Worst chunk RTF | Word match | Peak RSS |
|---|---|---|---|---|---|---|
| faster-whisper base int8 | 16.2 s | 0.24 | 3.98 s / 4.67 s | 0.31 | 0.898 | 754 MB |
| faster-whisper small int8 | 49.5 s | 0.74 | 12.5 s / **15.4 s** | **1.03** | 0.951 | 1190 MB |
| faster-whisper base float32 | 6.9 s | 0.10 | 1.50 s / 1.63 s | 0.11 | 0.893 | 912 MB |
| faster-whisper small float32 | 22.2 s | 0.33 | 3.74 s / 4.29 s | 0.29 | 0.932 | 1821 MB |
| openai-whisper base fp32 (today's app) | 25.4 s | 0.38 | 4.84 s / 5.33 s | 0.36 | 0.893 | 1484 MB |

Model load time was 0.5–1.7 s in every case. Base misspells the fantasy names ("Karak Don", "Borin's Dona bird", "Grok"). Small does better but still gets them wrong ("Karakdan", "Boran Stonibird", "Grug").

### 2.2 TTS: Kokoro-82M (`kokoro` 0.9.4, torch, voice `af_heart`, CPU)

The input was a 3-paragraph recap of 142 words, which produced 46.5 s of audio.

| Configuration | Generation time | RTF | First chunk | Peak RSS |
|---|---|---|---|---|
| Split per paragraph (`\n+`) | 11.4 s (17.5 s on the first run) | 0.25–0.38 | 3.5–4.1 s | **3889 MB** |
| Split per sentence | 16.6 s | 0.36 | n/a | 2058 MB (2.16 GB process max) |
| Model loaded and idle (after warm-up) | n/a | n/a | n/a | about 1.3–1.4 GB |

### 2.3 NLI contradiction (sentence-transformers `CrossEncoder`, CPU, 4 threads)

| Model | Per pair, batch 1 (median / p95) | Batch of 32 | Pairs/s | 50 pairs | Sanity (6 pairs) | Peak RSS |
|---|---|---|---|---|---|---|
| nli-deberta-v3-xsmall | 35 ms / 70 ms | 0.52 s | 61 | **0.71 s** | 4/6 | 844 MB |
| nli-deberta-v3-base | 213 ms / 321 ms | 1.81 s | 18 | **2.58 s** | 4/6 | 1140 MB |

Both models made the same two mistakes on the sanity set:
- "Borin is the king of Karak Dun" vs "Borin rules the dwarven city of Karak Dun": expected entailment, got neutral. This one is harmless.
- "Aldric swore an oath never to take a life" vs "Aldric ordered supper and asked about the weather": expected neutral, got **contradiction with p = 0.99 (xsmall) and 1.00 (base)**. This is a false positive above the planned 0.9 threshold, between sentences that share an entity.

Both models found all three real contradictions with p ≥ 0.97. These include "Mira died in the fire" vs "Mira greeted the party at the inn" (p = 0.998 / 1.0) and "Grukk cannot read" vs "Grukk read the inscription aloud".

### 2.4 Ollama structured extraction: skipped

Ollama was not reachable. `curl -s localhost:11434/api/tags` returned nothing (HTTP 000), there is no `ollama` binary, and there is no `docker` CLI, so the Compose stack is not running. I pulled no model, as the brief instructed. This needs to be re-run on the reference box with the stack up.

## 3. Verdicts against the provisional targets

### 3.1 Live STT: target is that each chunk is processed faster than its own duration

- **base: PASS** in both compute types. Int8 needs at most 0.31× the chunk duration, which leaves about 3× headroom even with the slow arm64 int8 path. Float32 needs 0.11×. A 15 s chunk comes back in 1.5–4.7 s, which fits the "2–4 s caption lag" estimate on this machine. On the target box, a 2–5× slowdown would put base int8 at about 0.6–1.5× RTF. That is marginal, so it **must be re-measured there**.
- **small: FAIL / marginal.** With int8 on arm64, one 15 s chunk took 15.4 s (RTF 1.03). Float32 passes (0.29), but its peak RSS is 1.8 GB. Small has no realistic headroom on a slower 8 GB box. It is also the only thing likely to fit next to a resident 7B model.
- int8 vs float32: on Apple Silicon float32 was 2.6–3.3× *faster* than int8. On x86 this is expected to flip. Make compute type a config setting (`int8` default, `float32` override) and do not hard-code it.
- faster-whisper vs openai-whisper base: at like-for-like accuracy, float32 is 3.7× faster on the full clip and int8 is 1.6× faster. Peak RSS falls from 1484 MB to 754–912 MB (−39% to −49%). The direction of the research claim holds. The exact 4× / −37% figures are not confirmed.

### 3.2 TTS recaps: target is RTF < 1

- **Speed: PASS.** RTF is 0.25–0.38, so a 45 s recap takes 11–17 s. That is fine for an async, cached job.
- **RAM: CONCERN.** Kokoro through the `kokoro` torch package uses about 1.3 GB at idle and about 2.1 GB peak when it synthesises one sentence at a time. Per-paragraph synthesis peaks at about 3.9 GB. A Q4 7B model already takes about 4–5 GB, so on an 8 GB box Kokoro must synthesise **one sentence per call**, run as a lazy sidecar, and never run at the same time as an LLM generation. kokoro-onnx is likely lighter but was not measured (see below).
- **espeak-ng / licence: the GPL code is installed automatically.** You do not need to install espeak-ng on the system. `pip install kokoro` pulls in `espeakng-loader` 0.2.4, which bundles a prebuilt `libespeak-ng` shared library and its data (about 20 MB, GPL-3.0+). kokoro-onnx depends on the same loader. The phonemizer path is misaki `en.G2P`: gold/silver lexicons plus spaCy `en_core_web_sm` POS tagging, then `misaki.espeak.EspeakFallback` (phonemizer-fork → libespeak-ng) for out-of-vocabulary words.
- **Without espeak, every fantasy name is silently dropped.** I ran with the fallback disabled, which is the commercial-edition configuration. Seven words vanished from the audio: Karak, Borin, Stonebeard, Grukk, Aldric, Dawnbreaker and dwarven. That is not acceptable for TTRPG recaps. The commercial edition needs a non-GPL out-of-vocabulary path. One candidate is a campaign pronunciation lexicon built from the entity table and fed to Kokoro's inline `[Word](/phonemes/)` override; this was not tested. Another is a separate-process espeak-ng after legal review.
- Dev-loop gotcha: the `espeakng-loader` 0.2.4 macOS arm64 wheel is broken. It hard-exits with `Error processing file '/Users/runner/work/.../espeak-ng-data/phontab'`, a path baked in from its CI build, and neither `ESPEAK_DATA_PATH` nor `set_data_path` fixes it. Linux containers are probably unaffected, but this was not verified. Also, spaCy's auto-download of `en_core_web_sm` fails inside a pip-less `uv venv`, so the model wheel has to be installed explicitly.

### 3.3 NLI: target is about 50 pairs per entry save in < 10 s

- **xsmall: PASS** at 0.71 s for 50 pairs, about 14× headroom. Even at 5× slower it would take about 3.5 s.
- **base: PASS** at 2.58 s for 50 pairs, about 4× headroom. At 5× slower it would be about 13 s and miss the target, so it needs a measurement on the target box.
- Always batch. Batch-1 calls cost 35 ms (xsmall) and 213 ms (base) each, against 8.5 ms and 57 ms per pair when batched.
- Quality: the two models were identical on this 6-pair set (too small to tell them apart). Both gave a confident false contradiction on a neutral pair that shares an entity. This supports the planned design: send p ≥ 0.9 pairs to the 7B to verify, and show a dismissible flag rather than a block.

### 3.4 Structured extraction: not measured (Ollama unavailable)

## 4. Recommendations

1. **STT: default to faster-whisper `base`**, with 15 s chunks (stay inside the 10–30 s range; shorter chunks lower the lag). Offer `small` only as an opt-in "accuracy" setting for offline or batch transcription, not for live mode, on 8 GB boxes. Expose `compute_type` as config. Fix fantasy-name accuracy with Whisper's `initial_prompt` / hotwords seeded from the campaign glossary rather than a bigger model (not measured here).
2. **NLI: default to `nli-deberta-v3-xsmall`**, batched at 32. Switch to `base` only if a labelled eval of at least 50 real canon pairs shows a clear accuracy gain. It costs about 3.6× the CPU for the same verdicts on this sample.
3. **TTS: Kokoro is fast enough.** Plan for about 2 GB per synthesis process with sentence-level chunking, and schedule it so it does not overlap LLM generation. Do not ship the commercial edition until there is a non-espeak plan for out-of-vocabulary words, because the names are the content. Next step: measure kokoro-onnx (int8 model) RSS on Linux, where the loader works.
4. **Re-run this exact suite on the 8 GB reference box** (x86, Docker stack up). The priorities are: int8 vs float32 for both Whisper sizes, NLI base at 50 pairs, Kokoro peak RSS, and the Ollama extraction test that was skipped here.

## 5. Reproduce

All scratch work lives outside the repo. The scripts are in the appendix.

```bash
B=$TMPDIR/bench; mkdir -p $B && cd $B
sysctl -n machdep.cpu.brand_string hw.memsize hw.ncpu
curl -s localhost:11434/api/tags; docker ps      # Ollama check (both absent here)

# envs
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python faster-whisper psutil sentence-transformers openai-whisper
uv venv --python 3.12 .venv-tts
uv pip install --python .venv-tts/bin/python kokoro soundfile psutil \
  "en_core_web_sm @ https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl"

# audio: speech.txt = the GM script (about 200 words, see appendix A)
say -f speech.txt -o clip.aiff
afconvert -f WAVE -d LEI16@16000 -c 1 clip.aiff clip.wav      # 67.1 s
.venv/bin/python -c "
import wave; w=wave.open('clip.wav'); sr=w.getframerate(); d=w.readframes(w.getnframes()); s=15*sr*2
for i in range(0,len(d),s):
    o=wave.open(f'chunk{i//s}.wav','wb'); o.setnchannels(1); o.setsampwidth(2); o.setframerate(sr); o.writeframes(d[i:i+s]); o.close()"

export OMP_NUM_THREADS=4
for s in base small; do for ct in int8 float32; do
  /usr/bin/time -l .venv/bin/python stt_fw.py $s $ct; done; done   # look for "maximum resident set size"
/usr/bin/time -l .venv/bin/python stt_ow.py
for n in xsmall base; do /usr/bin/time -l .venv/bin/python nli.py cross-encoder/nli-deberta-v3-$n; done
/usr/bin/time -l .venv-tts/bin/python tts_kokoro.py        # recap.txt = appendix A
```

### Appendix A: inputs

`speech.txt` (GM table talk, 67 s when spoken by `say`):
> Okay everyone, settle in, we are picking up where we left off last week. The party is standing at the gates of Karak Dun, and the dwarven sentries are not happy to see you. Borin Stonebeard steps forward and demands to know why a half-orc barbarian is carrying the royal seal. Grukk, what do you do? Grukk says he found it on a dead courier near the river, and he wants a reward. Roll me a persuasion check. Thirteen? With your bonus that is a fifteen. Borin narrows his eyes but lets you through. Inside the hall, Aldric the paladin notices the torches are burning green, which he has only seen once before, during the siege of Dawnbreaker. Veyra, our elven ranger, wants to check the shadows near the throne. Give me a perception roll. Natural twenty! You spot a cloaked figure slipping behind a pillar, clutching a black dagger with runes that glow faintly. The figure whispers something in an old tongue, and the green flames flare up all around you. Roll initiative, everybody. Aldric goes first with a nineteen, then Veyra, then the cloaked stranger, then Grukk. Aldric, the stranger is thirty feet away across the cracked marble floor. What is your move?

`recap.txt` (3 paragraphs separated by blank lines):
> Last time on our adventure, the party arrived at the iron gates of Karak Dun, where Borin Stonebeard and his sentries met them with drawn axes. Grukk talked his way past the guards with a stolen royal seal, claiming he had found it on a dead courier by the river.
>
> Inside the great hall, Aldric noticed the torches burning a sickly green, the same eerie flame he had witnessed during the siege of Dawnbreaker. Veyra's keen elven eyes spotted a cloaked figure slipping behind a pillar, clutching a black dagger etched with glowing runes.
>
> As the stranger whispered in a forgotten tongue, the green fire roared to life all around them. Steel was drawn, initiative was rolled, and the fate of the dwarven kingdom now hangs on what happens next. Will our heroes unmask the stranger before the flames consume the hall?

### Appendix B: scripts

`stt_fw.py` (argv: size, compute_type):
```python
import numpy as np, sys, time, wave, json, glob, re, difflib, psutil
from faster_whisper import WhisperModel
size = sys.argv[1]; CT = sys.argv[2] if len(sys.argv) > 2 else "int8"
dur = lambda p: (lambda w: w.getnframes() / w.getframerate())(wave.open(p))
def load_wav(p):
    w = wave.open(p); return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
t = time.perf_counter(); m = WhisperModel(size, device="cpu", compute_type=CT, cpu_threads=4); load = time.perf_counter() - t
def tr(p):
    a = load_wav(p); t = time.perf_counter()
    segs, _ = m.transcribe(a, beam_size=5, language="en", vad_filter=False)
    txt = " ".join(s.text for s in segs); return time.perf_counter() - t, txt
tr("chunk0.wav")  # warm-up
full_t, full_txt = tr("clip.wav"); D = dur("clip.wav")
chunks = [(p, round(dur(p), 1), round(lt, 2), round(lt / dur(p), 3)) for p in sorted(glob.glob("chunk*.wav")) for lt, _ in [tr(p)]]
ref = re.findall(r"[a-z']+", open("speech.txt").read().lower()); hyp = re.findall(r"[a-z']+", full_txt.lower())
match = sum(b.size for b in difflib.SequenceMatcher(None, ref, hyp).get_matching_blocks())
print(json.dumps(dict(model=f"faster-whisper {size} {CT}", load_s=round(load, 2), full_s=round(full_t, 2),
      full_rtf=round(full_t / D, 3), chunks=chunks, word_match=round(match / len(ref), 3))))
```

`stt_ow.py` is the same harness using `whisper.load_model("base", device="cpu")` and `m.transcribe(a, language="en", fp16=False, beam_size=5)`, with `torch.set_num_threads(4)`. It takes numpy input because ffmpeg is not installed.

`nli.py` (argv: model name):
```python
import sys, time, json, torch, numpy as np
torch.set_num_threads(4)
from sentence_transformers import CrossEncoder
m = CrossEncoder(sys.argv[1], device="cpu")
labels = [m.model.config.id2label[i].lower() for i in range(3)]   # contradiction, entailment, neutral
pairs = [
 ("Mira died in the fire at the Silver Stag.", "Mira greeted the party at the inn the next morning.", "contradiction"),
 ("Borin Stonebeard is the king of Karak Dun.", "Borin Stonebeard rules the dwarven city of Karak Dun.", "entailment"),
 ("The black dagger was destroyed in the forge at Dawnbreaker.", "Veyra drew the black dagger and stabbed the cultist.", "contradiction"),
 ("Aldric swore an oath never to take a life.", "Aldric ordered supper and asked about the weather.", "neutral"),
 ("Grukk cannot read.", "Grukk read the ancient inscription aloud to the group.", "contradiction"),
 ("The party left Karak Dun heading north.", "The party travelled north away from Karak Dun.", "entailment"),
]
ex = [(a, b) for a, b, _ in pairs]; m.predict(ex[:2])  # warm-up
probs = m.predict(ex, apply_softmax=True)
sanity = [(e, labels[int(np.argmax(p))], round(float(p[labels.index("contradiction")]), 3)) for (_, _, e), p in zip(pairs, probs)]
lat = []
for i in range(30):
    t = time.perf_counter(); m.predict([ex[i % 6]], batch_size=1); lat.append(time.perf_counter() - t)
b32 = (ex * 6)[:32]; times = []
for _ in range(5):
    t = time.perf_counter(); m.predict(b32, batch_size=32); times.append(time.perf_counter() - t)
t = time.perf_counter(); m.predict((ex * 9)[:50], batch_size=32); t50 = time.perf_counter() - t
print(json.dumps(dict(per_pair_ms_median=1000 * np.median(lat), per_pair_ms_p95=1000 * np.percentile(lat, 95),
      batch32_s=np.median(times), fifty_pairs_s=t50, sanity=sanity), default=float))
```

`tts_kokoro.py` (espeak fallback deliberately disabled; see §3.2):
```python
import time, json, numpy as np, soundfile as sf, torch
torch.set_num_threads(4)
from misaki import espeak
class NoEspeak:
    def __init__(self, *a, **k): raise RuntimeError("espeak fallback disabled")
espeak.EspeakFallback = NoEspeak          # KPipeline then logs "EspeakFallback not Enabled" and continues
from kokoro import KPipeline
pipe = KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M", device="cpu")
list(pipe("Warm up sentence.", voice="af_heart"))
text = open("recap.txt").read(); t = time.perf_counter(); first = None; audio = []; dropped = []
for r in pipe(text, voice="af_heart", split_pattern=r"\n+"):   # sentence split: r"(?<=[.?!])\s+"
    first = first or time.perf_counter() - t
    audio.append(r.audio.numpy())
    dropped += [tk.text for tk in (r.tokens or []) if tk.text.strip().isalpha() and not tk.phonemes]
gen = time.perf_counter() - t; wav = np.concatenate(audio); dur = len(wav) / 24000
sf.write("recap_kokoro.wav", wav, 24000)
print(json.dumps(dict(audio_s=dur, gen_s=gen, rtf=gen / dur, first_chunk_s=first, dropped=dropped)))
```
