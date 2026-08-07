# «Editor First» → extendo/nakedlunch: design-to-code audit

Date: 2026-07-31. Source: Claude Design project `35fea38e-63e1-4237-b353-281f9d8ef771`
(«Доработка дизайна и багов»), file `Editor First.dc.html` + `support.js` + `ВСТРАИВАНИЕ.md`.
Status: **analysis only, nothing written to code.**

Prose is in English per the standing session rule; every UI label is kept in Russian verbatim,
because those are the names the design and the owner actually use.

---

## 0. What was read, and the one honest gap

| File | Size | Complete? |
|---|---|---|
| `ВСТРАИВАНИЕ.md` | 3 KB | yes — the owner's own integration contract |
| `Editor First.dc.html` | 250 KB | **no — truncated at the 256 KiB API cap** |
| `support.js` | 66 KB | yes (DC runtime, generated, not project logic) |
| `Distillation Moment.dc.html` | 55 KB | yes |
| `Pipeline Redesign.dc.html` | 40 KB | yes |
| `Freestyle Optimized.dc.html` | 45 KB | yes |
| `Generator Unified.dc.html` | 125 KB | yes |
| `freestyle-engine.js` | 257 KB | no — truncated, but it is a minified Butterchurn bundle, not project logic |

**The gap, precisely.** `Editor First.dc.html` came back cut at exactly 262 144 bytes.
What survived: the entire template (lines 1–1295, i.e. every visible control) and 227 of the
class's members including the whole `api = {…}` boundary block and all generation/editor logic.
What was lost: the last ~6 helpers (`openPop`, `closePop`, `closeSub`, `docText`, `flash`,
`onGlobalKey`) and, more importantly, the trailing `renderVals()` method — the view-binding layer
that computes all **382** `{{ }}` bindings the template consumes.

Why this is tolerable: the sibling files (complete) show `renderVals()` is pure presentation glue —
it maps state to styles and wires handlers to the already-recovered methods. Every data-shaped
binding (`funnelRows`, `statRows`, `favRows`, `popItems`, `chainChips`, `genParams`, …) has its
field names visible in the template markup, which is intact. No behaviour was inferred that the
template does not literally show.

Chrome was unavailable this session, so the full file could not be fetched another way. If the
`renderVals()` body is ever needed verbatim, it must be re-exported below 256 KiB or pulled from a
logged-in browser.

---

## 1. Verdict in one paragraph

The design is a genuinely good, dense, and largely coherent interface — but its declared backend
boundary is **too narrow for extendo's actual product**. `ВСТРАИВАНИЕ.md` promises that swapping
seven `api.*` methods makes the app real. It does not: two of the seven map to existing endpoints,
one is partially backed, one should never have been a backend method at all, and three have no
data behind them anywhere. More consequentially, the boundary has **no parameter surface** — and
parameters (theme, six knobs, stanza spec, forced words) *are* extendo. Adopting the design as
literally specified would silently switch off most of what the last several months built.

None of this is fatal. It is a boundary-redesign problem, not a rewrite.

---

## 2. Three structural problems — verified directly, not inferred

These were checked against the design file by hand because each one changes the plan.

**2.1 There is no field to type a theme (тема).**
Verified: the strings `Тема`/`тема` occur exactly twice in the whole file — once as the
`aria-label` of the light/dark toggle (line 1067), once in a comment about scene profiles
(line 2965). `state.theme` is `'dark' | 'light'`, i.e. colour, not topic.

extendo's entire relevance layer hangs off a theme string: `clean.theme` (`core/clean.py:122`),
the `!слово` forced-word syntax (`clean.py:140` + `filters.py:461 _ensure_forced`), the cohesion
percentile target (`filters.py:300`), the per-stanza theme anchor (`filters.py:1238`) and
`literal_cap` anti-stuffing (`filters.py:305`). With no input, all of it is dead.

**2.2 There is no Генератор mode.**
Verified: the only tab values in the file are `editor` and `fs`. The word `Генератор` appears
**zero** times. `state.mode: 'gen'` and one `pipeMode` binding exist, but the shell is a two-tab
editor + freestyle.

The fast loop that is ~90% of real use — one stanza on screen, a prefetched buffer, Space/Enter
advancing with zero network, refill in the background, `mark_shown` at display
(`App.jsx:693/770/783`) — has nowhere to live. Note the sibling `Generator Unified.dc.html` *does*
design that mode; `Editor First` folded it into the document editor and the fast loop did not
survive the fold.

**2.3 Generated lines are never marked as shown.**
Verified: no `mark_shown` equivalent anywhere (the single `показан` hit is a CSS comment).
extendo's no-repeat guarantee depends on `POST /api/history/mark_shown` (`api/server.py:381`),
deliberately fired at display time so prefetched-but-unseen stanzas don't burn. Generating straight
into a document without that signal means every line stays eligible forever and will repeat.

---

## 3. The boundary: seven methods vs. reality

| `api.*` | Backing today | Verdict |
|---|---|---|
| `corpusTotal()` | `_nl_pool_counts()` `server.py:144`; surfaced in generate's funnel and `GET /api/nl/state` | **ЧАСТИЧНО.** Real value ≈1.97M active fragments, not the mock 1 016 828. No cheap standalone counter route; not synchronous. |
| `corpusSources()` | `GET /api/nl/state` → `sources:[{name, fragment_count, active, …}]` | **ЕСТЬ**, with a rename. Must filter by `active` or it won't sum to `corpusTotal`. 42 sources on disk, not 3. 503 when nakedlunch is absent — hide, don't error. |
| `poolSize()` | `_nl_pool_counts()` → `pool_available` | **ЧАСТИЧНО, and a repeat of a fixed bug.** `server.py:609-617` records that `pool_total` and `pool_available` were deliberately split after the collapsed single number was caught hiding where the volume went. One `poolSize` re-merges them. |
| `stanzaPool(roleKey)` | **none** | **НЕТ.** No role-keyed couplet pool exists; roles have no backend meaning at all. Nearest is `POST /api/generate`, which returns finished lines with `{text, rhyme, rhyme_span, syllables, template, classic, anchor, lemmas}` — not `[head, tail]` pairs. Must be replaced outright. |
| `wordSuggest(word, tab, rowIdx)` | **none** (partial data only) | **НЕТ ×4.** «рифмы»: needs a reverse word→rhyme index + stress for arbitrary typed words, but `ruaccent` is build-time-only. «по звуку»: no alliteration scoring exists. «синонимы»/«антонимы»: **no thesaurus in the repo at all** — the single largest missing data dependency; navec cosine cannot give antonyms. «строкой»: genuinely feasible today over `nl_rhyme.json`. |
| `rhymeFor(tail)` | partial (`scan.py:81`, `filters.py:914/932`) | **НЕТ / probably unnecessary.** Called per generated line, so a per-call HTTP round trip is not viable. Deeper: the design uses it to overwrite an already-chosen line's last word, whereas extendo selects lines *by* rhyme key from the start (`filters.py:1023`) — the existing mechanism is strictly better. |
| `runTitles()` | **none** | **Should not be a backend method.** Purely cosmetic; make it a client constant. |

**The missing eighth.** `ВСТРАИВАНИЕ.md` says "восемь методов" but lists seven, and the `api` object
defines seven. Worth confirming which one was dropped.

**The bigger boundary problem.** `stanzaPool` takes only a `roleKey`. There is no slot for theme,
the six knobs, the stanza spec, or forced words — so `chain`, `junctions`, `filters`, `threshold`,
`dissonance`, `params`, `profile`, `algo` and `seed` are all UI state wired to nothing. Replacing
`stanzaPool` with `POST /api/generate` changes the boundary's shape, not just its implementation.

Also: all seven are synchronous. extendo's generate is a blocking POST, ~0.4–0.5 s warm and ~2.2 s
cold. The design has no promise, no loading state and no error path anywhere, and `runPipe` builds
**50 documents in one synchronous loop**. Every call site must become async.

---

## 4. ЕСТЬ — connects with little or no backend work (14)

Флеш-сообщения · Избранное on a line + the list · фильтр банальности · слоги 8–9 ·
только точные рифмы · воронка отбора (real per-stage counts already exist, and are *better* than
the design's invented arithmetic) · строфа (⌘↵ → `/api/generate` with `shortlist = stanza.length`) ·
Строфа form card (24 forms, full CRUD, live editable — the design downgrades it to read-only) ·
алгоритм ▾ (→ `classic` knob) · Статистика (`/api/stats`) · Автосмена строки + speed ·
Следующая строка · loading/error/offline handling (already exists as honest demo mode) ·
`mark_shown` (exists in code, missing from the design — see 2.3).

## 5. ЧАСТИЧНО — exists but must be reshaped (27)

The ones that actually matter:

- **genParams (6 knobs).** Only 3 map (`Точность рифм`→rhyme_precision, `Мелодичность`→melody,
  `Банальность`→banality). `Метр` duplicates Мелодичность; `Разнообразие` is `_diversify`'s `div`,
  aliased to cohesion at `clean.py:200` and not independently settable; `Источники` has no
  counterpart. **Missing entirely: `real_text`, `classic`, `cohesion`** — the three with hard
  contracts at their extremes.
- **Диссонанс.** Declared in the design, read by nothing. extendo's `cohesion` *is* the dissonance
  axis and was rewritten three times to get there (DECISIONS 24/26/27). Bind the slider to
  `cohesion`; do not add a second dial.
- **Порог отсева.** Duplicates the banality knob (`filters.py:607 banal_ceiling`). Merge.
- **scheme() rhyme letters.** Design derives them from the last 2 normalized characters; extendo's
  `rhyme_key` is stress-based with vowel reduction and final devoicing, and every row already ships
  `rhyme` + `rhyme_span`. Use the shipped value or the letters will visibly disagree.
- **прогнать (runPipe).** Backend has no concept of N whole-song variants. Either request
  N×stanza-size and slice client-side, or add a `variants` parameter.
- **профиль генерации.** Full profile CRUD already ships — but it stores *stanza forms*
  (letters + syllable ranges), not chains of roles. Reshape onto it or add a second store.
- **история.** The data shape fits, but the semantics collide: in extendo история is a *hiding*
  mechanism (`corpus.py:190 hidden_set`); in the design it is a click-to-reinsert list.
- **Профили сцены / профили вида.** Design puts them in `localStorage`; `core/settings.py`'s own
  header and DECISIONS Round 26 record that opaque storage was explicitly rejected in favour of
  concrete files next to `corpus.json`. Also `state.runs` (up to 50 documents) into a ~5 MB quota.

## 6. НЕТ — must be built (38, of which 17 are L/XL)

**Documents subsystem (XL).** Sheets, folders, smart folders, trash + 30-day retention, vault path,
Finder reveal. Nothing document-shaped exists — `corpus.json` holds lines, not documents.
PLAN.md ФАЗА 1 specifies `.md` files in real folders and marks it unbuilt. Note
`api/server.py:763` is a catch-all static route, so every new `/api` path must be explicitly
registered or it 404s as a missing *file*.

**Roles and the chain (XL).** `Куплет/Припев/Хук/Бридж/Строфа` have no backend meaning, no
per-role corpus, no `KEYFOR` analogue. (`Строфа` has no key even in the design's own `KEYFOR` and
silently falls back to `verse`, so the «Вольная» preset is entirely verse-pool.) Junction modes
(`рифмовать стык / свободно / слом ритма`) likewise have no analogue.

**Thesaurus (XL).** синонимы/антонимы need a Russian thesaurus dataset. None present, none in
`requirements.txt`.

**Freestyle scene (XL×4).** The layered stage, the engine, mic/track, Butterchurn, preset
catalogue, camera, text post-processing, video recording. Two specific blockers: the design's
text-warp is the *raster/SVG displacement family that BACKLOG already rejected* after 8 revisions
in favour of MSDF geometry; and video recording has no save path, since pywebview has no downloads
manager and every file output must go through `window.pywebview.api.save_file`.

**Reproducible seed (L).** `state.seed` has no consumer. Even a seeded `generate()` isn't
reproducible: `filters.py` uses the global `random` module before every stable sort.

---

## 7. Regressions and conflicts with recorded decisions

Ranked by how much they'd cost if missed:

1. **Favourites die on edit.** `readDom` rewrites any hand-edited row with `fav:false`.
   `corpus.py:149` documents that unaccept is the *only* way a favourite disappears
   («никуда не пропадает никогда пока я сам не удалю»). Direct contradiction.
2. **The funnel regresses to invented numbers.** `_rich_funnel` (`server.py:156`) already returns
   true per-stage survivor counts for two pipelines; it was rebuilt precisely because of
   «никакой адекватной инфографики». `computeFunnel` hardcodes 0.82 / 1−0.42·threshold / 0.74 /
   0.58 / ×1.9 and shows one pipeline.
3. **The filter cascade is reimplemented client-side and worse** — `makeFsLines` uses a 3-word мат
   regex, `Math.random() < threshold·0.5` for banality, and raw vowel counting for syllables.
4. **«без мата» doesn't exist** and is shipped ON by default, priced into the funnel at ×0.82 —
   a number with no backing. The only content rejections are 4 hardcoded clichés and the owner's
   (currently empty) blacklist.
5. **`state.limit` is internally inconsistent** — labelled «строк за прогон», rendered as the final
   funnel stage, but `runPipe` treats it as variant count clamped 1..50. extendo's `shortlist` is
   genuinely a line count, 1..400.
6. **Chrome auto-hides on hover** — mockup 099 has two explicit corrections against exactly this:
   «история и избранное показываются всегда… без возможности закрыть» and «все топ бары вообще
   открываются не наведением а нажатием».
7. **Пайплайн as a header pill** — 099 says make it a permanent, non-closable right-hand tab in the
   editor, and put pipelines into the library filesystem as a folder.
8. **Tint/glow/glass/grain on editor chrome** contradicts the locked 099 palette (taken literally:
   pure white canvas, zero chroma, radius 6). Sanctioned for the freestyle scene, not the editor.
9. **Hand-rolled undo/redo** (80-entry JSON snapshots) vs PLAN ФАЗА 1: «undo/redo — готовый
   компонент, не самописный».
10. **Google Fonts in `<helmet>`** violates offline-first (`requirements.txt` invariants #1/#2);
    099 already records that CSP blocks CDN fonts.
11. **Three retention clocks conflated** into one «30 дней» string: sheet trash, generation-history
    retention (user-settable presets), and nakedlunch session retention (a *different* preset set).
12. **Naming collision.** In this codebase `nakedlunch` is the CLI at `~/nakedlunch` and the
    fragment corpus behind `core/nlbridge.py` — `/api/nl/*`, the `nl_mix` knob, the NL badge,
    `src:'nl'`. Using the word as the *editor tab's* name will collide throughout code and docs.
13. **Thread safety.** Flask runs `threaded=True` over mutable module globals with no locking; the
    single-window assumption is what keeps it safe. `runPipe`'s 50-variant burst and per-line
    `rhymeFor` calls both break it.

Two claims to disregard from the automated pass: `ВСТРАИВАНИЕ.md` and `freestyle-engine.js` were
reported "missing" — they exist, in the *design* project, not in the extendo repo. The observation
that the engine is an externally-injected bundle rather than the in-repo React component BACKLOG
plans for still stands.

---

## 8. Suggested order (not started — awaiting a decision)

1. **Settle the three structural questions first** (§2): where does the theme go, does Генератор
   survive as its own mode, where does `mark_shown` fire. Nothing else is safe to build first.
2. **Redraw the boundary.** Replace `stanzaPool` with `POST /api/generate` and give the boundary a
   parameter object. Make all of it async with loading/error states.
3. **Free wins.** Bind the real funnel, real `rhyme` letters, real stats, real stanza forms, real
   status widget — all already served.
4. **Decide roles.** Either invent a role→corpus mapping, or drop roles and keep stanza specs.
   This is the single biggest fork in the design.
5. **Documents subsystem** as `.md` files in real folders, per PLAN ФАЗА 1.
6. **`wordSuggest` in feasibility order:** «строкой» (buildable now) → «рифмы» (needs a prebuilt
   index or runtime `ruaccent`) → «по звуку» (new metric) → синонимы/антонимы (needs a dataset).
7. **Freestyle last**, and against BACKLOG's MSDF direction rather than the design's SVG warp.
