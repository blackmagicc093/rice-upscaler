# UPSCALE v1 — UI Redesign Spec (for implementation in OpenCode)

> Build a desktop app window (Windows-style) for an AI image upscaler.
> Dark theme + mint-green accent. Clean, balanced, professional.
> This spec is the single source of truth — implement exactly as described.
> Reference mockup image is attached for visual guidance, but follow the TEXT spec when they conflict.

---

## 0. READ FIRST — mistakes from the previous build (DO NOT repeat)

The previous implementation got these wrong. Each item shows WRONG → CORRECT:

1. **DPI dropdown defaulted to `300`.** WRONG. → CORRECT: on launch, the selected value MUST be the first option, `Default`. (Same for Format: must show `Default`, not `JPG`/`PNG`.) Set `selectedIndex = 0` explicitly; never auto-select the last option.
2. **The target-size field was labeled `Target MB:`.** WRONG. → CORRECT: the field MUST exist (it is an important feature) and its label MUST read exactly `Target Size (MB):` — not `Target MB`, not `Target size (MB)` with lowercase. It sits between PNG Compression and Scale (see §4b.5).
3. **`+ Add Files` rendered with a solid WHITE background.** WRONG. → CORRECT: it is an OUTLINE button — transparent background, 1px solid white-ish border (`--text-primary`), white text. It must NEVER be filled solid white. Same outline treatment must not accidentally become a "focused/active" solid state.
4. **An empty vertical scrollbar track was visible in the left panel with 0 files.** WRONG. → CORRECT: the file list shows NO scrollbar unless content actually overflows. Use `overflow-y: auto` (not `scroll`), and style the scrollbar thin and dark when it does appear.
5. **Bottom status bar buttons were clipped / cut off at the window edge.** WRONG. → CORRECT: the whole window is a flex column (`topbar / main / statusbar`); `main` is the ONLY flexible/scrolling area; the status bar is pinned at the bottom and must ALWAYS be fully visible. Minimum window size 1280×900. Nothing may overflow the viewport.
6. **An in-app header row (`✨ UPSCALE`) was rendered below the OS title bar.** WRONG. → CORRECT: use ONLY the native OS window-frame title, which already displays `UPSCALE`. Do NOT render any in-app header/title row at all — no logo row, no duplicate title, no in-app window controls.
7. **`+ Add Files` shows a white box with a second dark frame around it — the OLD button is still rendered underneath the new one (double-render / overlapping legacy UI).** WRONG. → CORRECT: rebuild from a clean component tree. DELETE every legacy button/field component first; each control must exist EXACTLY ONCE. Never layer a new control on top of or beside the old one. If `+ Add Files` renders white, the old component was not removed — remove it.
8. **Buttons and textboxes look flat and washed-out compared to the mockup (no visible borders, no depth).** WRONG. → CORRECT: apply the exact control finishing in §1b — visible 1px borders (`#3A4350`, lighter than panel borders so edges read against the panel), subtle vertical gradient on secondary buttons, inset shadow on textboxes, accent focus glow. Do not render borderless flat controls.

---

## 1. Design tokens

### Colors
| Token | Hex | Usage |
|---|---|---|
| `--bg-app` | `#14181E` | Window background |
| `--bg-panel` | `#1E242E` | Main panels (INPUT FILES, OUTPUT SETTINGS), top info bar, status bar |
| `--bg-input` | `#2A313C` | File cards, dropdown fields, path field, numeric field, secondary buttons |
| `--bg-dropzone` | `#1A222B` | Drag & drop zone fill (slightly tinted) |
| `--border-subtle` | `#2E3642` | Panel borders, card borders (1px) |
| `--border-input` | `#3A4350` | Textbox/dropdown/button borders (1px) — deliberately lighter than `--border-subtle` so field edges stay visible against `--bg-panel` |
| `--border-dashed` | `#35E0A6` | Drop zone dashed border (2px, dash 8px / gap 6px, radius 12px) |
| `--accent` | `#2FE6A7` | Primary mint-green: slider fill, value badges, START button, engine text, icons |
| `--accent-hover` | `#25C98F` | START button hover |
| `--accent-text-on` | `#0B0F14` | Text/icons on top of accent (dark) |
| `--track` | `#3A4350` | Slider track (unfilled part), gray |
| `--text-primary` | `#F2F5F7` | Headings, labels, values |
| `--text-secondary` | `#9AA4B2` | Helper text, meta info, placeholders |
| `--text-green` | `#2FE6A7` | Engine name text, status "Ready" text |
| `--danger-hover` | `#E5484D` | X (remove file) button hover |

### Typography
- Font: system UI stack (`Segoe UI` on Windows / `Inter` fallback). All text sans-serif.
- Section headers (`INPUT FILES`, `OUTPUT SETTINGS`): 15px, weight 700, letter-spacing 1.5px, `--text-primary`, with a 20px `--accent` outline icon to the left (image icon / folder icon).
- Field labels (`Format:`, `DPI:` …): 14px, weight 600, `--text-primary`.
- Body/meta text: 13px, `--text-secondary`.
- Value badges (`92%`, `6/9`, `1x`): 13px, weight 700, `--accent-text-on` on `--accent` pill.
- Native OS title bar text: `UPSCALE` (set via the OS window title — do not draw it yourself).

### Shape & spacing
- Panel corner radius: 12px. Buttons: 10px. Pills/badges: full radius.
- Page padding: 20px. Gap between the two main panels: 16px. Gap between top bar and panels: 14px. Bottom status bar margin-top: 14px.
- Panel inner padding: 20px.

### 1b. Control finishing — text & border effects (match the mockup exactly)

Apply these to EVERY interactive control. The mockup's premium feel comes from these details:

- **Text rendering (global):** `-webkit-font-smoothing: antialiased; text-rendering: optimizeLegibility;`
- **Textboxes / dropdowns / path field / numeric field:**
  - `background: var(--bg-input);`
  - `border: 1px solid var(--border-input);` (#3A4350 — must be visibly lighter than the panel background; the field edge must read clearly, never blend into the panel)
  - `box-shadow: inset 0 1px 2px rgba(0,0,0,.35);` (subtle inner depth)
  - Focus state: `border-color: var(--accent); box-shadow: 0 0 0 3px rgba(47,230,167,.15); outline: none;`
- **Secondary buttons** (`+ Add Folder`, `Clear All`, `Browse…`, `About`, `Cancel`, `Open Output Folder`):
  - `background: linear-gradient(180deg, #313845 0%, #272D38 100%);` (subtle vertical sheen — top slightly lighter)
  - `border: 1px solid var(--border-input);`
  - `box-shadow: 0 1px 2px rgba(0,0,0,.4);` (faint drop shadow = raised feel)
  - Hover: `border-color: var(--accent); color: var(--accent); box-shadow: 0 0 8px rgba(47,230,167,.25);`
  - Active/pressed: `transform: translateY(1px); box-shadow: none;`
- **Outline button** (`+ Add Files` only):
  - `background: transparent;` (never any fill — not white, not gray)
  - `border: 1px solid var(--text-primary);`
  - `box-shadow: 0 1px 2px rgba(0,0,0,.4);`
  - Hover: `border-color: var(--accent); color: var(--accent); box-shadow: 0 0 8px rgba(47,230,167,.25);`
- **Primary button** (`START UPSCALE`): flat `var(--accent)` fill, NO gradient (matches mockup). Hover: `var(--accent-hover)` + `box-shadow: 0 4px 16px rgba(47,230,167,.35);`
- **Value badges** (`92%`, `6/9`, `1x`): flat `var(--accent)` fill, NO gradient, no shadow.
- **Section headers** (`INPUT FILES`, `OUTPUT SETTINGS`): `letter-spacing: 1.5px;` with the accent outline icon — no text-shadow.
- **Engine pill text** (`AI Real-ESRGAN`): solid `var(--text-green)`, no glow.

---

## 2. Window title — native OS frame ONLY

- The OS window frame displays the title `UPSCALE` (set `title="UPSCALE"` on the native window).
- **Do NOT render any in-app header row.** No logo row, no duplicate `UPSCALE` text, no in-app minimize/maximize/close buttons, no "Pro v1.2" badge.
- The first visible in-app element below the OS frame is the top info bar (§3).

## 3. Top info bar

- Full-width strip, `--bg-panel`, radius 12px, padding 12px 16px, 1px border `--border-subtle`.
- Left: label `Engine:` (14px, `--text-secondary`, weight 600) + pill showing engine name `AI Real-ESRGAN`:
  - Pill: `--bg-input` background, 1px `--border-subtle` border, radius 10px, padding 8px 16px.
  - Engine name text: 14px, weight 700, color `--text-green` (`#2FE6A7`).
  - **Static text — not a dropdown, no chevron. No "Ready" text anywhere in this bar.**
- Right: single button `About ⓘ` (secondary button style, see §6). **No Preset / Settings / Help buttons.**

## 4. Main content — two-column grid

`grid-template-columns: 1fr 1.15fr; gap: 16px;` — this `main` area is `flex: 1` and `min-height: 0` inside the window flex column.

### 4a. LEFT panel — INPUT FILES (flex column)

1. **Section header**: image icon (accent) + `INPUT FILES`.
2. **Drop zone** (margin-top 16px, fixed height 240px, does NOT stretch):
   - Dashed 2px `--border-dashed` border, radius 12px, `--bg-dropzone` fill.
   - Centered content: cloud-upload outline icon (accent, 44px), then `Drag & drop images here` (17px, weight 700, `--text-primary`), then `or click to browse • supports JPG, PNG, WEBP` (13px, `--text-secondary`).
   - Clicking anywhere in the zone opens the file picker.
3. **File list** (`flex: 1`, `min-height: 0`, `overflow-y: auto`, margin-top 14px, gap 10px):
   - One card per queued image: `--bg-input` background, radius 10px, padding 10px 12px, horizontal layout: 44×44px thumbnail (radius 8px, object-fit cover) → filename (14px/600/primary) over meta line `1920×1080 • 1.4 MB` (12px/secondary) → circular `✕` button at right (32px, `--text-secondary`, hover bg `--danger-hover` + white icon).
   - **Empty state (0 files): the list area is simply blank — no cards, no scrollbar, no placeholder text.** (`overflow-y: auto`, never `scroll`.)
   - Scrollbar styling (only when overflowing): 8px wide, thumb `--border-subtle`, track transparent.
4. **Action buttons row** (margin-top 14px, gap 10px, pinned at panel bottom):
   - `＋ Add Files` — OUTLINE style: transparent background, 1px solid `--text-primary` border, `--text-primary` text. **Never solid-filled.**
   - `＋ Add Folder` — secondary style. `🗑 Clear All` — secondary style.
   - Height 40px, padding 0 18px, radius 10px, 14px weight 600.
   - **No "Remove" button** (per-file ✕ covers it).

### 4b. RIGHT panel — OUTPUT SETTINGS

Rows are label-left / control-right, vertical gap 22px. Labels 170px wide, controls flex-fill. **Row order is fixed:**

1. **Format** — custom dropdown, initial value `Default` (`selectedIndex = 0`). Options in order: `Default`, `JPG`, `PNG`.
2. **DPI** — custom dropdown, initial value `Default` (`selectedIndex = 0`). Options in order: `Default`, `150`, `300`.
   - Dropdown style (see §1b for full finishing): `--bg-input`, `1px solid var(--border-input)` (#3A4350 — visibly lighter than the panel), `inset 0 1px 2px rgba(0,0,0,.35)`, radius 10px, height 44px, padding 0 14px, 14px text `--text-primary`, chevron `▾` at right in `--text-secondary`. Focus: accent border + `0 0 0 3px rgba(47,230,167,.15)` glow. Closed state shows only the selected value.
3. **Image Quality** — slider, range **1–100**, default **92**.
4. **PNG Compression** — slider, range **0–9**, default **6**.
   - Slider spec (all sliders): track height 6px, radius full; unfilled part `--track` (gray); filled part `--accent` (green) from left edge up to the knob; knob = 18px circle, `--accent` fill with 3px `--bg-panel` outer ring; value badge at right = `--accent` pill (min-width 56px, height 30px, centered dark bold text: `92%`, `6/9`). Green fill + knob move together while dragging.
5. **Target Size (MB)** — label text MUST be exactly `Target Size (MB):` (capital T, capital S, capital MB in parentheses). Control: numeric input field, width ~110px (does NOT stretch full width), `--bg-input`, `1px solid var(--border-input)`, inset shadow per §1b, radius 10px, height 44px, 14px `--text-primary`, empty by default (placeholder `--text-secondary`, e.g. `—`).
   - Behavior: empty = feature disabled (no target). When a number is entered, the encoder aims for that output file size in megabytes. Accept positive numbers (decimals allowed, e.g. `2.5`).
6. **Scale** — slider, discrete steps **1x, 2x, 3x, 4x, 5x, 6x, 7x, 8x**, default **1x** (knob at far left). Same slider styling; badge shows current step (`1x`). Below the slider, one centered helper line (13px, `--text-secondary`):
   - With an image queued: `Output: 1920×1080 • no change` → updates live (e.g. 2x → `Output: 3840×2160 • ~4x pixels`).
   - With no image queued: `Output: — (select images to preview)`.
   - **Scale sits directly above Output Folder** (order: Format → DPI → Image Quality → PNG Compression → Target Size (MB) → Scale → Output Folder).
7. **Output Folder** — label + path field (flex-fill, `--bg-input`, `1px solid var(--border-input)`, inset shadow per §1b, radius 10px, height 44px, 13px text, e.g. `C:\Users\User\Pictures\Upscaled`, empty = placeholder `--text-secondary`) + `📁 Browse…` secondary button.
   - **No "Files will be saved…" helper line.**

**There is no OPTIONS section.**

## 5. Bottom status bar (pinned, never clipped)

- Full-width `--bg-panel` panel, radius 12px, padding 14px 18px, `flex-shrink: 0`.
- Left block: `Ready: 0 files queued ●` — "Ready:" in `--text-green` weight 700, rest `--text-primary` 13px; the `●` dot is `--accent`. (With files: `Ready: 2 files queued • Est. time: ~12s ●`.) Below: `0%` (13px/700/primary) + progress bar (flex-fill, height 8px, `--track` bg, `--accent` fill, radius full).
- Right block (gap 10px, vertically centered): `⊕ Cancel` (secondary), `📁 Open Output Folder` (secondary), `🚀 START UPSCALE` (primary: `--accent` bg, `--accent-text-on` 15px/800 text, padding 0 28px, height 48px, radius 10px; hover `--accent-hover`; subtle shadow).

## 6. Button styles (shared — full finishing in §1b)

- **Secondary**: `linear-gradient(180deg, #313845, #272D38)` bg, 1px solid `var(--border-input)` border, `--text-primary` 14px/600, height 40px, padding 0 18px, radius 10px, `0 1px 2px rgba(0,0,0,.4)` shadow; hover: border `--accent`, text `--accent`, `0 0 8px rgba(47,230,167,.25)` glow; active: translateY(1px), no shadow.
- **Outline** (`+ Add Files` only): transparent bg (**never any fill**), 1px solid `--text-primary` border, `--text-primary` text; hover per §1b. **Never render this button with a solid fill.**
- **Primary** (START): flat `--accent` (no gradient), as defined in §5.
- Disabled state (e.g. START with 0 files): opacity 0.4, no pointer events. (Cancel can stay enabled; it just resets.)

## 7. Behaviors

- **Clean rebuild:** implement from a fresh component tree. Before adding the new controls, remove ALL legacy buttons/fields from the previous UI. Every control in §4–§5 must exist exactly once — verify no duplicates in the DOM (this caused the double-rendered `+ Add Files`).
- Launch defaults: Format=`Default`, DPI=`Default`, Image Quality=`92`, PNG Compression=`6`, Target Size (MB)=empty (disabled), Scale=`1x`, queue empty → status `Ready: 0 files queued`, START disabled (opacity 0.4).
- Dragging files over the drop zone: border becomes solid `--accent` + soft `--accent` glow.
- Removing a file via its ✕ updates queue count, est. time, progress reset.
- Output Folder empty → files save next to source with `_upscaled` suffix, never overwrite.
- Target Size (MB): when empty, encoder uses quality/compression settings normally; when set, output is tuned toward that MB target.
- Sliders: keyboard accessible (arrow keys), value badge updates live; Scale snaps to the 8 discrete steps.
- Window: `display: flex; flex-direction: column; height: 100vh; min-height: 900px; min-width: 1280px;` — only `main` and the file list may scroll internally.

## 8. Explicitly EXCLUDED (do not implement)

- In-app header/title row (the OS frame already shows `UPSCALE`); "Pro v1.2" badge; Preset / Settings / Help buttons; standalone "Remove" button; OPTIONS section (Denoise / Face Enhancement); "Files will be saved…" helper text; Engine dropdown chevron; "Ready" text next to Engine; second set of window controls inside the app; empty scrollbar tracks; solid-white Add Files button; any label reading `Target MB` (the correct label is `Target Size (MB):`); duplicate/overlapping legacy controls from the old UI; borderless flat textboxes or buttons (every control must use the §1b finishing).

## 9. Layout skeleton (for the AI coder)

```
<OS window frame>  title="UPSCALE" (native — you do not draw this)
<body> (bg --bg-app, padding 20px, font stack,
        display flex, flex-direction column, height 100vh,
        min-height 900px, min-width 1280px)
  <topbar> Engine: [AI Real-ESRGAN pill] ........ [About ⓘ]
  <main> (flex:1, min-height:0, grid 1fr 1.15fr, gap 16px)
    <panel> INPUT FILES  (flex column)
      <dropzone/>            (fixed 240px)
      <file-list/>           (flex:1, overflow-y:auto, empty = blank)
      [＋ Add Files][＋ Add Folder][🗑 Clear All]
    </panel>
    <panel> OUTPUT SETTINGS
      Format:            [Default ▾]      (options: Default/JPG/PNG)
      DPI:               [Default ▾]      (options: Default/150/300)
      Image Quality:     [slider 1–100] [92%]
      PNG Compression:   [slider 0–9]   [6/9]
      Target Size (MB):  [___]           (numeric, ~110px, empty = off)
      Scale:             [slider 1x–8x]  [1x]
                         Output: — (select images to preview)
      Output Folder:     [path........] [📁 Browse…]
    </panel>
  </main>
  <statusbar> (flex-shrink:0)
      Ready: 0 files queued ●
      0% [progress........]
      [⊕ Cancel][📁 Open Output Folder][🚀 START UPSCALE]
  </statusbar>
</body>
```

## 10. Acceptance checklist (verify before finishing)

- [ ] DPI shows `Default` on launch (not `300`); Format shows `Default`.
- [ ] `Target Size (MB):` field exists between PNG Compression and Scale, with EXACTLY that label; empty by default.
- [ ] `+ Add Files` is transparent with a light border (not solid white).
- [ ] No visible scrollbar in the file list when 0–2 files are queued.
- [ ] Status bar fully visible at 1280×900 with all three buttons unclipped.
- [ ] NO in-app header row — the only `UPSCALE` title is the native OS window title.
- [ ] Scale slider sits directly above Output Folder; no OPTIONS section below it.
- [ ] Engine pill is static green text, no chevron, no "Ready" beside it.
- [ ] Every control exists exactly once — no ghost/duplicate/overlapping legacy buttons (inspect the DOM, especially `+ Add Files`).
- [ ] Textboxes/dropdowns show a visible 1px `#3A4350` border with subtle inset shadow (not blending into the panel); focus shows the accent glow.
- [ ] Secondary buttons show the subtle vertical gradient + visible border + faint shadow (not flat); `+ Add Files` is transparent with a light border.
