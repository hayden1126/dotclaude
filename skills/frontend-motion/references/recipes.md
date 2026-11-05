# Motion and polish recipes

Start from the recipe, then adapt. The rules behind each value are in `../SKILL.md`.

```css
:root {
  --ease-out: cubic-bezier(0.23, 1, 0.32, 1);
  --ease-in-out: cubic-bezier(0.77, 0, 0.175, 1);
  --ease-drawer: cubic-bezier(0.32, 0.72, 0, 1);
}
```

`data-starting-style` and `data-ending-style` are Base UI's attributes; use the equivalent state hook of your component library. The recipes show the full motion. Every one that moves, scales or blurs also takes the reduced-motion fallback below.

## Reduced-motion fallback

The opacity fade runs for everyone. Movement, scale and blur join it only without the preference.

```css
.panel {
  transition: opacity 150ms var(--ease-out);
}

@media (prefers-reduced-motion: no-preference) {
  .panel {
    transition-property: opacity, translate, scale, filter;
    transition-duration: 200ms;
  }
}
```

In Tailwind, prefix movement, scale and blur utilities with `motion-safe:`. In Motion, branch and keep only opacity:

```tsx
const reduce = useReducedMotion();
const hidden = reduce
  ? { opacity: 0 }
  : { opacity: 0, transform: "translateY(12px)", filter: "blur(4px)" };
```

## Press

```css
.button {
  transition-property: scale;
  transition-duration: 150ms;
  transition-timing-function: var(--ease-out);
}

@media (prefers-reduced-motion: no-preference) {
  .button:not(:disabled):active {
    scale: 0.96;
  }
}
```

```tsx
// Tailwind
<button className="transition-transform duration-150 ease-[cubic-bezier(0.23,1,0.32,1)] motion-safe:enabled:active:scale-[0.96]">
  Click me
</button>

// Motion
<motion.button
  whileTap={disabled || reduce ? undefined : { transform: "scale(0.96)" }}
  transition={{ duration: 0.15, ease: [0.23, 1, 0.32, 1] }}
  disabled={disabled}
>
  Click me
</motion.button>
```

`scale` takes the label and icons along, which is what reads as a physical press. `:active` is a real press on touch, so it needs no hover gate.

Where the button has no variant API to carry the opt-out, use a `static` prop:

```tsx
const tapScale = "motion-safe:enabled:active:scale-[0.96]";

function Button({ static: isStatic, className, children, ...props }) {
  return (
    <button
      className={cn(
        "transition-transform duration-150 ease-[cubic-bezier(0.23,1,0.32,1)]",
        !isStatic && tapScale,
        className,
      )}
      {...props}
    >
      {children}
    </button>
  );
}
```

## Dropdown, popover, menu, select

Scales out of its trigger, not out of thin air.

```css
.popover {
  transform-origin: var(--transform-origin); /* Base UI supplies this */
  transition:
    opacity 200ms var(--ease-out),
    transform 200ms var(--ease-out);
}

.popover[data-starting-style],
.popover[data-ending-style] {
  opacity: 0;
  transform: scale(0.95);
}

.popover[data-ending-style] {
  transition-duration: 150ms;
}
```

## Entering from display: none

An element toggled from `display: none` has no previous style to transition from. `@starting-style` supplies one, and `allow-discrete` keeps it rendered through the exit. The open state's duration applies on enter, the closed state's on exit.

```css
[popover] {
  opacity: 0;
  scale: 0.95;
  transition-property: opacity, scale, display, overlay;
  transition-duration: 150ms;
  transition-timing-function: var(--ease-out);
  transition-behavior: allow-discrete;
}

[popover]:popover-open {
  opacity: 1;
  scale: 1;
  transition-duration: 200ms;
}

@starting-style {
  [popover]:popover-open {
    opacity: 0;
    scale: 0.95;
  }
}
```

`@starting-style` and discrete `display` transitions are Baseline 2024. `overlay` is Chromium only, and browsers without support show and hide instantly.

## Tooltip

```css
.tooltip {
  transform-origin: var(--transform-origin);
  transition:
    transform 125ms var(--ease-out),
    opacity 125ms var(--ease-out);
}

.tooltip[data-starting-style],
.tooltip[data-ending-style] {
  opacity: 0;
  transform: scale(0.97);
}

/* Once one tooltip is open, neighbours open instantly */
.tooltip[data-instant] {
  transition-duration: 0ms;
}
```

The initial delay prevents accidental activation. After that, skipping both the delay and the animation makes the whole toolbar feel faster.

## Modal

The one popover that stays centered, with the backdrop's opacity alongside it so they read as one surface.

```css
.modal {
  transform-origin: center;
  transition:
    opacity 250ms var(--ease-out),
    transform 250ms var(--ease-out);
}

.modal[data-starting-style],
.modal[data-ending-style] {
  opacity: 0;
  transform: scale(0.96);
}

.modal[data-ending-style] {
  transition-duration: 150ms;
}

.backdrop {
  transition: opacity 250ms var(--ease-out);
}
```

## Drawer or sheet

The destination state's duration applies, so this opens over 500 ms and closes over 200 ms. Add drag and it becomes a gesture problem: see Drag to dismiss.

```css
.drawer {
  transform: translateY(0);
  transition: transform 500ms var(--ease-drawer);
}

.drawer[data-closed] {
  transform: translateY(100%);
  transition: transform 200ms var(--ease-out);
}
```

## Toast

Prefer a library's toast. Motion values if you are tuning one:

```css
.toast {
  opacity: 1;
  transform: translateY(0);
  transition:
    opacity 250ms var(--ease-out),
    transform 250ms var(--ease-out);

  @starting-style {
    opacity: 0;
    transform: translateY(100%);
  }
}

.toast[data-ending-style] {
  opacity: 0;
  transform: translateY(100%);
  transition-duration: 200ms;
}
```

Without `@starting-style`, fall back to a mount flag:

```jsx
useEffect(() => { setMounted(true); }, []);
// <div data-mounted={mounted}>
```

When toasts stack and the list reflows, the opacity change has to work against the height change. There's no formula for that pair: adjust until it feels right, then check again the next day.

## Accordion

One of the few animations that costs layout on every frame, so keep it short. Measure the content height in JS (or use a headless primitive that supplies it) rather than animating to `auto`.

```css
.content {
  overflow: hidden;
  transition:
    height 200ms var(--ease-out),
    opacity 200ms var(--ease-out);
}
```

## Group entrance

A list the user sees occasionally, or a staged hero. Never a list they scroll past all day.

| | Delay between items | Offset | Blur |
| --- | --- | --- | --- |
| List or grid | 50 ms (30 to 80 ms) | `8px` | none |
| Staged hero (title, description, actions) | 100 ms | `12px` | `4px` |
| Short display headline, split into words | 80 ms | `12px` | `4px` |

The hidden state lives in the `from` keyframe, so an item whose animation never runs stays visible. Reduced motion keeps only the opacity keyframe.

```css
.stagger-item {
  animation: fade-in 300ms var(--ease-out) both;
}

@media (prefers-reduced-motion: no-preference) {
  .stagger-item {
    animation-name: fade-in-up;
  }
}

.stagger-item:nth-child(2) { animation-delay: 100ms; }
.stagger-item:nth-child(3) { animation-delay: 200ms; }

@keyframes fade-in {
  from { opacity: 0; }
}

@keyframes fade-in-up {
  from {
    opacity: 0;
    transform: translateY(12px);
    filter: blur(4px);
  }
}
```

```tsx
const item = {
  hidden: { opacity: 0, transform: "translateY(12px)", filter: "blur(4px)" },
  visible: {
    opacity: 1,
    transform: "translateY(0px)",
    filter: "blur(0px)",
    transition: { duration: 0.3, ease: [0.23, 1, 0.32, 1] },
  },
};

function PageHeader() {
  return (
    <motion.div
      initial="hidden"
      animate="visible"
      variants={{ visible: { transition: { staggerChildren: 0.1 } } }}
    >
      <motion.h1 variants={item}>Welcome</motion.h1>
      <motion.p variants={item}>A description of the page.</motion.p>
      <motion.div variants={item}>
        <Button>Get started</Button>
      </motion.div>
    </motion.div>
  );
}
```

## Exit

```tsx
// Subtle, the default
<motion.div
  exit={{
    opacity: 0,
    transform: "translateY(-12px)",
    filter: "blur(4px)",
    transition: { duration: 0.15, ease: [0.23, 1, 0.32, 1] },
  }}
/>

// Full, only where the destination carries meaning
<motion.div
  exit={{
    opacity: 0,
    transform: "translateX(-100%)",
    transition: { duration: 0.2, ease: [0.23, 1, 0.32, 1] },
  }}
/>
```

```css
/* Good: subtle exit */
.item-exit {
  opacity: 0;
  transform: translateY(-12px);
  transition: opacity 150ms var(--ease-out), transform 150ms var(--ease-out);
}

/* Bad: dramatic exit that steals focus */
.item-exit {
  opacity: 0;
  transform: translateY(-100%) scale(0.5);
  transition: all 400ms ease-out;
}

/* Sometimes correct: remove at once when motion adds no information */
.item-exit {
  display: none;
}
```

## Interruptible state

| | CSS transitions | CSS keyframes |
| --- | --- | --- |
| Behavior | Interpolate toward the latest state | Run on a fixed timeline |
| Interrupted | Retarget and reverse | Snap or restart |
| Use for | Hover, toggle, open and close | Sequences that run once |

```css
/* Good: clicking again mid-animation reverses smoothly */
.panel {
  transform: translateX(-100%);
  transition: transform 200ms var(--ease-out);
}
.panel.open {
  transform: translateX(0);
}

/* Bad: closing mid-animation snaps */
.panel.open {
  animation: slideIn 200ms var(--ease-out) forwards;
}
```

## High-frequency hover

```css
/* Good: a minimal transition, gated */
@media (hover: hover) and (pointer: fine) {
  .row:hover {
    background-color: var(--surface-hover);
    transition: background-color 100ms ease;
  }
}

/* Bad: every hover replays a full entrance */
.row:hover .row-icon {
  animation: bounceIn 500ms;
}
```

## Skip animation on first render

`initial={false}` suits icon swaps, toggles, tabs and segmented controls: anything with a default state on page load. Around a first-time entrance it skips that entrance entirely.

```tsx
// Bad: initial={false} skips the staggered page enter
<AnimatePresence initial={false}>
  <motion.div initial="hidden" animate="visible" variants={...}>
    ...
  </motion.div>
</AnimatePresence>
```

## Theme switch

Inject a stylesheet that turns off every transition, force a style flush so the new colors commit while it applies, then remove it after the next frame.

```tsx
"use client";

import { useEffect } from "react";

export function DisableThemeTransitions() {
  useEffect(() => {
    const mql = window.matchMedia("(prefers-color-scheme: dark)");

    const handleChange = () => {
      const style = document.createElement("style");
      style.append(
        document.createTextNode(
          "*,*::before,*::after{transition:none !important}"
        )
      );
      document.head.append(style);

      void document.body.offsetHeight; // forces a synchronous style flush

      requestAnimationFrame(() => {
        requestAnimationFrame(() => style.remove());
      });
    };

    mql.addEventListener("change", handleChange);
    return () => mql.removeEventListener("change", handleChange);
  }, []);

  return null;
}
```

That covers the OS-level change. An in-app toggle needs the same steps around its own flip: apply the override, change the theme, flush and remove. `next-themes` ships this as `disableTransitionOnChange`.

## Hold to confirm

For destructive actions where a plain click fires too easily. `linear` is correct: the fill is a progress indicator, and progress shouldn't ease.

```css
.overlay {
  clip-path: inset(0 100% 0 0);
  transition: clip-path 200ms var(--ease-out); /* release: snappy */
}

.button:not(:disabled):active .overlay {
  clip-path: inset(0 0 0 0);
  transition: clip-path 2s linear;             /* press: slow and deliberate */
}

.button:not(:disabled):active {
  scale: 0.96;
}
```

## Tab indicator with a color transition

Only for tabs switched occasionally, such as a settings or marketing page. App navigation tabs switch instantly. Duplicate the tab list, style the copy as the active state, clip it so only the active tab shows, and animate the clip. Text and background change in sync because they are one element being revealed.

```css
.tabs-active-copy {
  clip-path: inset(0 60% 0 20%); /* driven by the active tab's position */
  transition: clip-path 250ms var(--ease-in-out);
}
```

## Scroll reveal

Marketing surfaces only. Trigger with `IntersectionObserver`, or Motion's `useInView` with `{ once: true, margin: "-100px" }`. Fire it once.

```css
.reveal {
  clip-path: inset(0 0 100% 0);
  transition: clip-path 600ms var(--ease-in-out);
}

.reveal[data-visible] {
  clip-path: inset(0 0 0 0);
}
```

## Drag to dismiss

Springs, not durations, because the user can reverse mid-motion.

```js
// Dismiss on a flick, not just on distance
const timeTaken = Date.now() - dragStartTime.current;
const velocity = Math.abs(swipeAmount) / timeTaken;

if (Math.abs(swipeAmount) >= SWIPE_THRESHOLD || velocity > 0.11) {
  dismiss();
}

// Set transform on the dragged element directly
element.style.transform = `translateY(${distance}px)`;

// Settle with a spring so an interrupted drag keeps its velocity
{ type: "spring", duration: 0.5, bounce: 0.2 }
```

- **Pointer capture** once the drag starts, so it continues when the pointer leaves the element.
- **Multi-touch protection:** `if (isDragging) return` on new touch points, or switching fingers makes the element jump.
- **Damping past boundaries:** beyond a natural edge the element moves less the further it goes.
- **Friction, not a wall:** allow the over-drag with rising resistance rather than refusing it.

## Masking a crossfade that won't settle

When two states overlap visibly and no easing or duration fixes it, blur the seam, so the eye reads one transformation instead of two objects swapping. Stay under `20px`: heavy blur is expensive, especially in Safari.

```css
.content {
  transition:
    filter 200ms ease,
    opacity 200ms ease;
}

.content.transitioning {
  filter: blur(2px);
  opacity: 0.7;
}
```

## Programmatic, without a library

WAAPI gives JS control with CSS-grade performance, interruptible, at no bundle cost.

```js
element.animate(
  [{ clipPath: 'inset(0 0 100% 0)' }, { clipPath: 'inset(0 0 0 0)' }],
  { duration: 600, fill: 'forwards', easing: 'cubic-bezier(0.77, 0, 0.175, 1)' }
);
```

## Icon swap

Check `package.json`. Import from `"motion/react"` when `motion` is installed, or `"framer-motion"` when that is. Where both exist, follow the imports the nearest components use. Where neither is present, use the CSS version and add no dependency.

```tsx
import { AnimatePresence, motion, useReducedMotion } from "motion/react";

function IconButton({ isActive, icon: Icon }) {
  const reduce = useReducedMotion();
  const hidden = reduce
    ? { opacity: 0 }
    : { opacity: 0, transform: "scale(0.25)", filter: "blur(4px)" };
  return (
    <button>
      <AnimatePresence initial={false} mode="popLayout">
        <motion.span
          key={isActive ? "active" : "inactive"}
          initial={hidden}
          animate={reduce ? { opacity: 1 } : { opacity: 1, transform: "scale(1)", filter: "blur(0px)" }}
          exit={hidden}
          transition={{ type: "spring", duration: 0.3, bounce: 0 }}
        >
          <Icon />
        </motion.span>
      </AnimatePresence>
    </button>
  );
}
```

Without Motion, both icons stay mounted in one grid cell, so enter and exit both animate and the larger icon sets the size.

```tsx
const layer = cn(
  "[grid-area:1/1] transition-[opacity,filter,scale] duration-300",
  "ease-[cubic-bezier(0.2,0,0,1)]",
  "motion-reduce:scale-100 motion-reduce:blur-[0px]"
);
const shown = "scale-100 opacity-100 blur-[0px]";
const hidden = "scale-[0.25] opacity-0 blur-[4px]";

function IconButton({ isActive, ActiveIcon, InactiveIcon }) {
  return (
    <button>
      <span className="grid place-items-center">
        <span className={cn(layer, isActive ? shown : hidden)}>
          <ActiveIcon />
        </span>
        <span className={cn(layer, isActive ? hidden : shown)}>
          <InactiveIcon />
        </span>
      </span>
    </button>
  );
}
```

Tailwind 4's `scale-*` writes the `scale` property, so `transition-[...scale]` animates it. Tailwind 3's writes `transform`, so name `transform` instead.

| Animate | Don't animate |
| --- | --- |
| Infrequent swaps: play to pause, like to liked, copy to copied | Hover-revealed actions in list rows |
| Icons in a toolbar that appears on selection | Tab and navigation icon swaps |
| Loading and success indicators | Decorative or always-visible icons |

## Icon stroke, state and direction

| Adjacent text | Rendered stroke width |
| --- | --- |
| Regular (400), 14 to 16px | `1.5px` |
| Medium or semibold (500 to 600) | `2px` |
| Bold (700), or an emphasized standalone icon | `2.5px` |

The widths are rendered pixels. A 24px-grid icon drawn at 16px scales its stroke by 16/24, so `stroke-width="2"` paints about `1.33px`. Use the library's absolute-stroke option, or `vector-effect: non-scaling-stroke`. Where the library has no stroke variants, keep its native stroke and use size or color for emphasis.

```tsx
<button className="flex items-center gap-2 font-semibold">
  <Plus size={16} strokeWidth={2} absoluteStrokeWidth />
  New project
</button>
```

```css
/* One SVG, recolored per state, with the project's color tokens */
.icon-button { color: var(--icon-muted); }
.icon-button[aria-pressed="true"] { color: var(--icon-active); }
.icon-button:disabled { opacity: 0.4; }

@media (hover: hover) and (pointer: fine) {
  .icon-button:hover { color: var(--icon-strong); }
}
```

```tsx
// Outline by default, fill for active: the variant communicates state
<TabIcon variant={isActive ? "solid" : "outline"} />
```

Where a set ships per-size grids (`16`, `20`, `24`), use the grid that matches the render size: a 24px drawing scaled to 16px lands off the pixel grid and renders soft. Icon-only buttons need an accessible name.

| Flip under RTL | Don't flip |
| --- | --- |
| Back and forward arrows, navigation chevrons | Logos and brand marks |
| Text-block glyphs for alignment, lists and indent | Checkmarks |
| Speaker and volume waves | Physical objects such as clocks, cups and pencils |
| Directional glyphs such as "send" | Media playback, which stays LTR by convention |

Use one mechanism per element, because two flips can compound back to unflipped. Analyze composite icons part by part: a badge may keep its position while the base glyph flips.

```css
[dir="rtl"] .icon-directional {
  scale: -1 1;
}
```

```tsx
<ChevronRightIcon className="rtl:-scale-x-100" />
```

## Concentric radius

```css
/* Good: outer = inner + padding */
.card {
  border-radius: 20px; /* 12 + 8 */
  padding: 8px;
}
.card-inner {
  border-radius: 12px;
}
```

```tsx
<div className="rounded-2xl p-2">       {/* 16px radius, 8px padding */}
  <div className="rounded-lg">          {/* 8px radius = 16 - 8 */}
    ...
  </div>
</div>
```

## Shadow ring

Three layers in light mode: a 1px ring, lift, then ambient depth. Depth shadows vanish on dark backgrounds, so dark mode keeps one white ring. The transparent border keeps the box the same size as the border it replaces, and forced-colors mode paints it.

```css
:root {
  --shadow-border:
    0px 0px 0px 1px oklch(0 0 0 / 0.06),
    0px 1px 2px -1px oklch(0 0 0 / 0.06),
    0px 2px 4px 0px oklch(0 0 0 / 0.04);
  --shadow-border-hover:
    0px 0px 0px 1px oklch(0 0 0 / 0.08),
    0px 1px 2px -1px oklch(0 0 0 / 0.08),
    0px 2px 4px 0px oklch(0 0 0 / 0.06);
}

/* Redefine under the project's dark selector */
--shadow-border: 0 0 0 1px oklch(1 0 0 / 0.08);
--shadow-border-hover: 0 0 0 1px oklch(1 0 0 / 0.13);

.card {
  border: 1px solid transparent;
  box-shadow: var(--shadow-border);
  transition: box-shadow 150ms ease;
}

@media (hover: hover) and (pointer: fine) {
  .card:hover {
    box-shadow: var(--shadow-border-hover);
  }
}
```

## Image outline

`outline` rather than `border`, because it never changes the image's size. At `-1px` it sits just inside the edge and follows the corner radius. Never a palette near-black such as `#111827`.

```css
:root {
  --image-outline: oklch(0 0 0 / 0.1);
}
/* Redefine under the project's dark selector */
--image-outline: oklch(1 0 0 / 0.1);

.content-image {
  outline: 1px solid var(--image-outline);
  outline-offset: -1px;
}
```

```tsx
<img
  className="outline outline-1 -outline-offset-1 outline-black/10 dark:outline-white/10"
  src={src}
  alt={alt}
/>
```

## Transition and compositing

`transition: all` animates properties nobody meant to, such as colors on a theme flip. Tailwind's bare `transition` is a curated list, but still covers more than most elements change. In Tailwind 4, `transition-transform` covers `transform, translate, scale, rotate`, and in Tailwind 3 only `transform`. Mixing takes the bracket syntax:

```tsx
<button className="transition-[scale,background-color] duration-150">
```

`will-change` promotes an element to its own layer ahead of time, and each layer costs memory, so never add it preemptively.

| Property | Worth `will-change` |
| --- | --- |
| `transform`, `translate`, `scale`, `rotate`, `opacity`, `filter` | Yes |
| `clip-path` | Rarely: compositing it is not reliable across browsers |
| `top`, `left`, `width`, `height`, `background`, `border`, `color` | No |

`will-change` on a transform property or `filter` makes the element the containing block for its `position: fixed` descendants, so a fixed modal or tooltip inside it stops tracking the viewport. Any of these also creates a stacking context, which can reorder `z-index` against siblings.
