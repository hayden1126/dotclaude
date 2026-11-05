---
name: frontend-motion
description: Use when adding or changing animation, motion, transitions or micro-interaction polish in a web UI (hover, press, enter and exit, modals, drawers, toasts, stagger, springs, reduced motion), when asked to make an interface feel smoother or more alive, and for surface polish such as nested border radii, shadows, image outlines and icon states. Gives the decision order and exact values, including when the right answer is no animation.
---

# Frontend motion

Make the decisions in the order that determines whether motion feels right, then apply the surface and icon rules. Two failures, and the first is worse: animating something that shouldn't animate, and animating the right thing with the wrong ingredients (`ease-in` on an entrance, `scale(0)`, keyframes on a toast, a sluggish dropdown).

Recommend one answer in one line with its reason, then write the code. Zero lines of code is a valid result. Polish never outranks a broken interaction.

- **Run the sequence in order.** Steps 1 and 2 gate everything after them.
- **Values are exact.** `cubic-bezier(0.4, 0, 0.2, 1)` is not `--ease-out`, and `0.95` is not `0.96`. Only the optical nudges and the concentric padding cutoff are judged by eye.
- **Extend the project, don't fork it.** Reuse its `--ease-out`, duration scale, tokens and component library, and match its motion language where no rule here gives a value. A deliberate, consistent convention (no shadows at all) is a preference. The same detail done two ways is a defect.

Load `references/recipes.md` before writing any of these, and start from the recipe: press, dropdown, tooltip, modal, drawer, toast, accordion, group entrance, exit, hold to confirm, tab indicator, scroll reveal, drag to dismiss, icon swap, theme switch, shadow or image outline.

## The build sequence

### 1. Should this animate at all?

| Frequency | Decision |
| --- | --- |
| 100+ times a day (keyboard shortcuts, command palette toggle, keystrokes) | No animation. Stop here. |
| Tens of times a day (row hover, list navigation, tab switch) | Instant, or at most 150 ms on `opacity` or `background-color` |
| Occasional (modals, drawers, toasts) | Standard animation |
| Rare or first-time (onboarding, success, empty state, a view's first load) | The delight budget lives here |

Keyboard-initiated actions are a disqualifier, not a judgment call. If the request fails this gate, say so and offer the non-motion alternative: an instant state change or a static affordance.

### 2. What is the purpose?

Name one before continuing. Can't name it? Don't build it.
- **Feedback:** the interface heard the user.
- **Spatial consistency:** where something came from or went.
- **State indication:** a state change made legible.
- **Preventing a jarring change:** bridging content that would otherwise teleport.
- **Explanation:** how something works (marketing and onboarding only).
- **Delight:** only at the rare or first-time tier.

Data the user is reading or acting on doesn't move for style. Every animated state change also leaves a static cue (color, icon or label), so motion is never the only feedback.

### 3. Pick the tool: walk down, stop at the first that fits

| Need | Tool |
| --- | --- |
| Hover, press, color, a state toggled by class or attribute | CSS transition |
| Entry on mount, no JS state | CSS `@starting-style` |
| Predetermined motion that must stay smooth while the page loads | CSS animation (off the main thread) |
| Programmatic control, no library | WAAPI (`element.animate()`) |
| Springs, layout animation, exit animation, gesture-driven values | Motion (`motion.dev`) |

Never install a library for a fade or an icon swap. If the task needs a component rather than an animation (toast, drawer, menu, dropdown), prefer an existing accessible component library over hand-rolling: a hand-rolled dropdown is how you lose focus management.

### 4. Pick the properties

- **`transform` and `opacity` only.** `width`, `height`, `margin`, `padding`, `top` and `left` re-run layout. `clip-path` is the sanctioned third; `height` is tolerated only for accordions.
- **Name them.** `transition-property: scale, opacity`, never `all`.
- **Never `scale(0)`.** Panels start from `scale(0.95)` with `opacity: 0`. Icon swaps are the one exception, at `0.25`.
- **`transform-origin` at the trigger** for popovers, dropdowns, menus and tooltips (`var(--transform-origin)` in Base UI). Modals stay centered.
- **Percentages in `translate()`** are relative to the element itself. Prefer `translateY(100%)` over hardcoded pixels for a full slide.
- **In Motion, use the full transform string.** `animate={{ transform: "translateX(100px)" }}` is hardware accelerated; the `x`, `y` and `scale` shorthands drop frames under load.
- **Set `transform` on the element directly.** Driving a child through a CSS variable on its parent recalculates styles for every child.
- **`will-change` only after you see first-frame stutter,** naming the animated property. Limit it to transform properties, `opacity` and `filter`.

### 5. Easing and duration, or a spring

| Situation | Easing |
| --- | --- |
| Entering, exiting, press, and the default | `--ease-out` |
| Moving or morphing on screen | `--ease-in-out` |
| Drawer or sheet | `--ease-drawer` |
| Hover or color change | `ease` |
| Constant motion (marquee, progress) | `linear` |

```css
--ease-out: cubic-bezier(0.23, 1, 0.32, 1);
--ease-in-out: cubic-bezier(0.77, 0, 0.175, 1);
--ease-drawer: cubic-bezier(0.32, 0.72, 0, 1);
```

Never `ease-in` on UI: it delays the moment the user is watching. The built-in `ease-out` keyword is too weak, so "ease-out" here always means the token. Need another curve? Take it from easing.dev or easings.co rather than inventing one.

| Element | Duration |
| --- | --- |
| Press | 150 ms |
| Tooltip | 125 ms |
| Dropdown, popover, select, accordion | 200 ms |
| Toast, modal | 250 ms |
| Drawer | 500 ms open, 200 ms close |
| Exit, unless listed above | 150 ms |
| Group entrance per item, infrequent icon cross-fade | 300 ms |
| Marketing or explanatory | Longer is fine (scroll reveal 600 ms) |

UI durations stay under 300 ms; modals and drawers may reach 500 ms. The 300 ms row is the only other exception, because both are infrequent by definition.

- **Press:** scale `0.96` over 150 ms `--ease-out`, never on disabled. Give the component an opt-out where the motion would distract, through its variant API or a `static` prop.
- **Stagger:** lists 30 to 80 ms between items (50 ms unless you have a reason). A staged hero entrance splits into semantic chunks (title, description, actions) 100 ms apart, each with opacity, `4px` blur and `12px` `translateY`. Never stagger routine interactions, and never let a stagger hold up input.
- **Spring** when the motion is drag with momentum, a gesture the user can reverse (it carries velocity through the interruption), or decorative mouse-tracking. Default `{ type: "spring", duration: 0.5, bounce: 0 }`. Bounce 0.1 to 0.3 only for drag-to-dismiss and deliberately playful moments.

### 6. Interruption and exit

- **Transitions, not keyframes, for anything triggered rapidly.** Transitions retarget from the current value; keyframes restart or snap. Keep keyframes for sequences that run once.
- **Exits are shorter and smaller than enters:** opacity, `4px` blur and a fixed `-12px` `translateY` over 150 ms.
- **Slide fully out only where the destination carries meaning** (a drawer closing, a swiped toast, a card returning to a list), and then leave the way it came, over 200 ms. Remove instantly where motion adds no information.
- **Asymmetric timing where the user is deciding:** a hold-to-confirm fill runs 2 s `linear`, its release 200 ms `--ease-out`.
- **Skip state animation on first render:** `initial={false}` on an `AnimatePresence` around a state swap, never around an intentional entrance. Check on a full page refresh.

### 7. Reduced motion and pointer gating

These ship with the animation, every time.
```css
.panel { transition: opacity 150ms var(--ease-out); }

@media (prefers-reduced-motion: no-preference) {
  .panel { transition-property: opacity, translate, scale, filter; transition-duration: 200ms; }
}
```

Movement, scale and blur run only under `no-preference`. Under reduced motion, cross-fade opacity rather than removing the element instantly: fewer and gentler, not zero. In Tailwind use `motion-safe:`. In Motion, branch on `useReducedMotion()` and keep only opacity; `<MotionConfig reducedMotion="user">` alone leaves `filter` running.

Gate hover with `@media (hover: hover) and (pointer: fine)`, because `:hover` latches after a tap on touch. Where a control draws its own pressed state, also set `-webkit-tap-highlight-color: transparent`. More hover and touch mechanics: `frontend-ui-discipline`, if present.

## Surfaces

- **Concentric radius.** Where nested surfaces share a visible, even inset: outer radius = inner radius + padding + border width. Past `24px` of padding, or with deliberately asymmetric padding, treat them as separate surfaces.
- **Shadows for elevation, borders for structure.** Where a border exists only for depth, use layered transparent `box-shadow`. Keep borders on dividers, table cells, selected states and form inputs (whose boundary needs 3:1 contrast). Keep focus rings. Forced colors drops every `box-shadow`, so keep `border: 1px solid transparent` under a shadow ring.
- **Image outlines** are `1px`, inset `1px`, in pure `oklch(0 0 0 / 0.1)` light and `oklch(1 0 0 / 0.1)` dark. A tinted neutral shows as a colored fringe. Skip transparent artwork such as logos.
- **Theme switch:** disable all transitions for the swap, force a style flush, restore after the next frame. Otherwise every color transition fires at once and the switch smears.
- **Overlays:** `overscroll-behavior: contain` on scrollable dialogs, drawers, menus and side panels.
- **Optical nudges:** where geometric centering looks off, give a button `2px` less padding on its icon side and shift a play triangle `2px` toward its point, then judge by eye. Fix asymmetric glyphs in the SVG. More: `ui-alignment`, if present.

## Icons

- **Cross-fade infrequent swaps** (play to pause, copy to copied): scale `0.25` to `1`, opacity `0` to `1`, blur `4px` to `0px`. With Motion, `{ type: "spring", duration: 0.3, bounce: 0 }`. Without it, keep both icons in the DOM and cross-fade over `300ms` with `cubic-bezier(0.2, 0, 0, 1)`. Tab icon swaps and hover-revealed row actions don't animate.
- **Stroke tracks the adjacent text:** rendered `1.5px` at weight 400, `2px` at 500 to 600, `2.5px` at 700.
- **One SVG, recolored per state.** `currentColor`, with hover, selected and disabled from CSS color and opacity. Never separate assets. Outline by default, fill for active.
- **Sizing:** one library per surface, inline icons at `1em` to `1.25em`, always SVG, tested at the smallest size they render.
- **RTL:** under `dir="rtl"` mirror only icons whose meaning follows reading direction (back and forward, list glyphs, send). Never logos, checkmarks or media playback.

## Never ship

| Never | Instead |
| --- | --- |
| Animation on a keyboard shortcut or a 100+ a day action | No animation |
| `transition: all`, `transition-all`, `will-change: all` | Name the changing properties |
| `ease-in` on a UI element, built-in `ease-out` on a deliberate animation | `--ease-out` |
| UI duration over 300 ms with no reason | The duration table |
| `transform-origin: center` on a trigger-anchored popover | `var(--transform-origin)` (modals exempt) |
| Keyframes on toasts or toggles, `animation:` on `:hover` or `.open` | A transition on the same properties |
| `scale(0)`; animating `width`, `height`, `margin`, `padding`, `top`, `left` | `scale(0.95)`; `transform`, `opacity` |
| Motion `x`, `y`, `scale` props | Full `transform` string |
| Press below `0.96` (`active:scale-95`, `whileTap`), or with no disabled exclusion | `0.96` on `enabled:active:` or `:not(:disabled):active` |
| `bounce:` above 0 outside drag-to-dismiss and playful moments | `bounce: 0` |
| Everything entering at once | List stagger, 30 to 80 ms |
| `opacity: 0` in a base rule that only an `animation` reveals | Hidden state in the `from` keyframe, `animation-fill-mode: both` |
| Plain `:hover`, or Tailwind 3 `hover:`, outside the pointer query | `@media (hover: hover) and (pointer: fine)` |
| Movement, scale or blur with no reduced-motion guard, or motion as the only cue | Gate it and cross-fade opacity; add a static cue |
| Color transitions plus a theme toggle with no suppression | The theme-switch recipe, or `disableTransitionOnChange` |
| Padded parent and child with the same radius | Add the padding to the outer radius |
| `box-shadow: 0 0 0 1px` ring with no `border` beside it | `border: 1px solid transparent` |
| `outline-slate-*`, `outline-zinc-*` or a hex outline on `img` | `outline-black/10`, `dark:outline-white/10` |
| `fill="#..."` or `stroke="#..."` inside an icon SVG | `currentColor` |
| `overflow: auto` on a dialog, drawer or menu with no `overscroll-behavior` | `overscroll-behavior: contain` |

## Check the feel

Without a browser, read every state from the code with its durations and easings, and say what you couldn't check. With one, walk each state and replay at 10% speed in the Animations panel. Test gestures on a real device. When feel can't be settled from code (a spring's bounce, a toast's opacity against its reflow), say so instead of guessing at a value.

Adapted from two MIT-licensed skills: see `NOTICE`.
