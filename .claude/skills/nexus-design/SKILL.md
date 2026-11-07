---
name: nexus-design
description: Frontend design that doesn't look AI-made. Use for any UI work: building, redesigning, restyling, polishing or reviewing a page, landing page, dashboard, app screen, component, form or layout, in any stack (HTML/CSS, React, Next.js, Tailwind). Also when Collins says a page looks generic, cheap, templated, "AI", or the spacing/padding is off.
---

# Nexus design

A screen is done when it could only belong to this product. Clean but generic is the next template, not a win.

The brief wins. If Collins pins a style, font, color or reference site, follow it exactly, even if it's on the banned list below.

## 1. Pick the mode (decides how bold to be)

| Mode | What the visitor does | Examples | Ambition shows as |
|---|---|---|---|
| Persuade | Decides and acts | Landing, pricing, marketing | One bold visual idea, real imagery, strong type |
| Operate | Finishes a task | App, dashboard, admin, booking flow, forms | Precision, density, familiar patterns, speed |
| Read | Understands | Docs, articles, help | Measure, hierarchy, calm |
| Experience | Looks at the work | Portfolio, showcase | The work fills the screen, UI recedes |

Pick the mode from the screen, not the company. A booking app's landing page is Persuade; its seat picker is Operate.

## 2. Direction before code (write it, 8 lines max)

- **Product:** what it does, for whom, one plain sentence.
- **Character:** 2–3 concrete words ("fast, exact, a little warm"). Banned: clean, modern, sleek, minimal, premium, futuristic. They describe every template.
- **World:** the place or material it belongs to (matatu booking → road, route maps, ticket stubs, Nairobi street light). The world tints the neutrals, picks the accent and the visual.
- **Moment:** the ONE place that gets rich color and craft (a live seat map, a ticket, a real chart). Everything else stays quiet.
- **Signature:** one small detail only this product has, used consistently (a route line, a live status dot).
- **Tokens:** 4–6 named hex values, 1–2 typefaces with roles, radius, spacing density.
- **Layout:** one-line concept per screen, plus an ASCII wireframe if the layout isn't obvious.

Then the **template check**: would you produce this same plan for a different product? If yes, change the part that's generic and say what you changed.

"Futuristic / 10K website" means precision and one strong idea, not neon. For tech, software, gaming and fintech you may spend the boldness on ONE effect (a shader or WebGL hero, a live product demo, one scroll moment). For local businesses and services: real photos, flat color, great type, no effects.

## 3. Spacing (where AI slop shows first)

- Everything on a **4px grid**. Use a scale: `4 8 12 16 20 24 32 40 48 64 80 96 128`. No `13px`, no `mt-[11px]`.
- **Proximity = grouping.** Space inside a group < space between groups. More space above a heading than below it (e.g. 48 above, 16 below).
- **Rhythm, not monotony:** mix tight and generous gaps on purpose. One value everywhere makes everything equal weight.
- **Padding by density:** buttons 10–12 × 16–20; inputs 10–12 × 12–16; compact panels/sidebars 12–16; cards 20–24; page edges 16 (mobile) / 24–32 (tablet) / 32–64 (desktop); landing sections 64–96 (mobile) / 96–160 (desktop) vertical.
- **Same thing, same size:** every row in a list shares one height and gap; every card in a row shares one padding.
- **Equal edges:** every block sits on the same left and right content lines. Max content width ~1200–1280 for marketing, 1440–1600 for apps. No sideways scroll at any width.
- **Nested radius:** inner = outer − padding (min 4). Controls 8–10, cards 12–16, panels 14–20. Not everything is a pill.
- Use `gap` for sibling spacing instead of margins on children.
- **Touch targets ≥ 44×44px** with ≥ 8px between them, even if the visible mark is smaller.

## 4. Type

- 1 family, or 2 that are clearly different (e.g. a display face + a text face, or text + mono for data). Pick it for the character; don't default to Inter/Roboto/Arial unless it's the brand. Self-host or use Google Fonts with `font-display: swap`.
- A real scale (e.g. `12 14 16 18 20 24 30 36 48 60 72`). Body 16px minimum (14 only in dense app UI), line-height 1.5 for body, 1.1–1.2 for display.
- Body measure **65–75 characters**. Display max ~6rem.
- Hierarchy from size and color first; weights 400/500, 600 for rare emphasis. No 800–900 walls of bold.
- Tight tracking only on large display text (to −0.04em). Never negative tracking on small text.
- Sentence case. No ALL-CAPS tracked labels.
- Numbers: `font-variant-numeric: tabular-nums`, one format across the screen (`KES 1,200`, not `KES 1200.00` next to it).
- `text-wrap: balance` on headings.

## 5. Color

- One **neutral ramp tinted toward the world** (not pure grey, not pure black): background, raised surface, border, 3 text roles (primary, secondary, muted).
- **One accent**, used rarely: the primary action, the selection, the number that matters. Semantic colors (success, error) only carry meaning and are toned to fit.
- Rich color lives only inside the Moment.
- Contrast: body text ≥ 4.5:1, large text ≥ 3:1, including text on the accent.
- Borders: hairlines, the text color at 6–12% opacity.
- Shadows: neutral, soft, small, with a real offset and blur. Dark themes get depth from surface steps, not shadows.
- Light or dark: pick from where the person uses it (a matatu conductor in sunlight = light, high contrast), not from the category.
- Theme the browser parts too: `::selection`, `caret-color`, focus ring, scrollbar, `text-underline-offset`.

## 6. Layout

- **Hero:** say what's sold, to whom, plus one hard fact, in the first screen. One primary action, at most one secondary. The visual is the real product (a coded preview with plausible data) or a real photo, never decorative blobs.
- Prefer an **asymmetric split** (text one side, visual ≥ half the width) or text above a large product view. Fully centered stacks only for short heroes with no visual.
- Long headlines align left.
- Nav: logo, links, one button. Log in is a text link. Collapses to one menu button on mobile.
- Vary the grid: one wide element next to a narrow one beats 3 identical cards. Repeated cards only when the content truly is equivalent.
- Apps: real proportions (sidebar 240–280, fluid content), never a narrow centered column.
- **Mobile first**, check at 390, 768, 1024, 1440. On mobile: one column, reading order, buttons full width, dense previews simplified (fewer rows), not zoomed down. No text under 11px.
- Reserve space for images and async content (`aspect-ratio`, fixed heights) so nothing jumps (CLS < 0.1).

## 7. Components and states

- Every interactive thing has **hover, focus-visible, active, disabled, loading**. Every data view has **empty and error** states. An empty state tells you what to do next.
- One button pair (primary + secondary), one card style, one link style, one icon set.
- Icons: one library (the project's, else lucide), one size (16/18/20) and one stroke. They take the text color. **No emoji as icons.**
- Forms: visible labels (never placeholder-only), errors next to the field saying what's wrong and how to fix it, helper text where needed, correct `type`/`inputmode`/`autocomplete`.
- Stat cards: label, number, change *with what it's compared to* ("+12% vs last week"). No decorative sparklines.
- Charts: one main chart; line for trends, bars for comparison. One accent for the series that matters, the rest neutral.

## 8. Motion

- One authored moment (a page-load sequence or one reveal). Not a fade-up on every section.
- Motion that answers the user is good: hover = quick color/surface change, press = scale to ~0.98, menus fade and move 4–8px, numbers tween.
- Animate only `transform` and `opacity` (plus `clip-path`/`filter` if smooth). Never width, height, top, left or margins. No `transition-all`.
- One easing: `cubic-bezier(0.22, 1, 0.36, 1)` (ease-out). Durations: 120–180ms for feedback, 200–300ms for entering, exits faster than entrances.
- Linked cards lift ≤ 2px; photos zoom ≤ 1.03 inside their frame. No tilt, no bounce, no infinite pulses on things that aren't live.
- Respect `prefers-reduced-motion`: everything rests and nothing stays hidden.

## 9. Copy

- Headlines say what it does for whom; they shouldn't fit another product. Buttons are verb + object ("Book seat", not "Submit"); the action keeps its name through the flow ("Book seat" → "Seat booked").
- No hype (seamless, supercharge, unlock, revolutionize, AI-powered), no exclamation marks, no greeting headlines ("Welcome back, Collins! 👋").
- No unverifiable claims ("10,000+ happy users") unless Collins confirms they're real.
- Mock data looks real: Kenyan names, KES amounts, real routes. Never `Lorem`, `[X]` or `123,456`.
- Errors name the problem and the fix. They don't apologize.

## 10. Banned AI tells (unless the brief asks)

- Purple/violet/blue gradients, gradient text, glows, neon borders, colored shadows, blobs and orbs behind content.
- Cream background + serif + terracotta accent. Black + one acid-green accent. Identical rounded cards with the same grey shadow everywhere.
- Eyebrow labels above every heading. ALL-CAPS tracked labels. `01 / 02 / 03` unless it's a real sequence. `A · B · C` meta strings. `→` on every button.
- The hero-metric template (huge number, tiny label, gradient accent).
- Glassmorphism as decoration. Thick colored `border-left` on cards. Hard offset shadows (`4px 4px 0`) outside a real neobrutalist brief.
- Monospace as a "techy" costume. Emoji icons. Badges like `New ✨` or `Beta 🚀`.
- Scroll-triggered fade-ins on every card. Parallax. Carousels and auto-rotating tabs.
- Stock photos passed off as the client's product or people. Invented reviews or logos.

## 11. Build

Start from tokens, then components, then pages. Put tokens in one place (CSS variables or `tailwind.config`):

```css
:root {
  --space-1: 4px; --space-2: 8px; --space-3: 12px; --space-4: 16px; --space-5: 20px;
  --space-6: 24px; --space-8: 32px; --space-12: 48px; --space-16: 64px; --space-24: 96px;
  --radius-control: 8px; --radius-card: 14px;
  --ease: cubic-bezier(0.22, 1, 0.36, 1);
  --dur-fast: 150ms; --dur-base: 240ms;
  /* --bg --surface --border --text --text-2 --text-3 --accent: from the direction */
}
```

No raw hex or one-off px values inside components. Watch CSS specificity: section and element selectors that cancel each other's padding are a classic bug.

Spend boldness in one place. Before calling it done, remove one decoration.

## 12. Verify (on the rendered page, not in your head)

If a browser is available (Playwright, or the dev server plus screenshots), look at 390, 768 and 1440 in one batch, fix everything, then look again. Otherwise check the code against this list:

- [ ] Direction written; template check passed
- [ ] All spacing on the 4px scale; equal things equal; edges line up; no sideways scroll at 390
- [ ] One neutral ramp, 3 text roles, one accent; contrast ≥ 4.5:1
- [ ] Type: 1–2 families, real scale, 65–75ch body, tabular numbers, sentence case
- [ ] Every control has hover/focus/active/disabled/loading; data views have empty/error states
- [ ] Touch targets ≥ 44px; labels on every input
- [ ] Motion: transform/opacity only, one easing, reduced-motion respected
- [ ] Nothing from the banned list
- [ ] Swap test: put another product's name on it. If it still fits, push the copy, visual and signature harder.

Report in 5 lines or fewer: the direction, what's verified (widths checked), what wasn't, and the assets Collins must supply (photos, logo).

---
Synthesized from: Anthropic [frontend-design](https://github.com/anthropics/skills) (Apache-2.0), [impeccable](https://github.com/pbakaus/impeccable) by Paul Bakaus (Apache-2.0), [unslop](https://github.com/heydamir/unslop) by Damir Sokolovsky (CC BY 4.0), [taste-skill](https://github.com/Leonxlnx/taste-skill) (MIT), [ui-ux-pro-max](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) (MIT). Rewritten and condensed for Nexus.
