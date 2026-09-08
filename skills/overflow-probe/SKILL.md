---
name: overflow-probe
description: Find and fix horizontal overflow on a page at a target width, and measure a whole set of pages at once. Use when a page scrolls sideways on a phone, when an audit reports a scrollWidth wider than the viewport, or before shipping any page at 390px. Türkçe tetikleyiciler - telefonda yana kayiyor, mobilde tasiyor, 390da bozuluyor, yatay kaydirma var.
---

# Overflow probe

A page whose `scrollWidth` exceeds its `clientWidth` scrolls sideways on a phone.
This is how to find what causes it, fix it, and prove the fix on every page in a
tree. Written by the website lane on 2026-09-08 after five fabrika units.

## Measure it correctly, or the number is fiction

Three ways to get a wrong number, all of which happened on the day this was
written:

1. **Load fresh at the target width.** Resizing a page that is already open
   reports a different number, because canvases and SVGs sized at load do not
   re-lay-out. Cutfill read 493 on a fresh 390 load and 708 after a resize from
   1440. Set the viewport, then navigate.
2. **Bust the cache on every load.** After editing the file, the browser serves
   the copy it already has and the fix looks like it failed. Append `?v=<n>` and
   change it each time. Letterrun read 514 after the fix landed on disk, for
   this reason alone.
3. **Kill the scrollbar in a harness.** An iframe with a classic scrollbar
   reports `clientWidth` 378 rather than 390, so two pages looked narrower than
   they were. Set `scrolling="no"` on the iframe.

`getBoundingClientRect()` is the wrong instrument here: it counts clipped and
scrollable content, so it accuses elements that are contained, and a full-width
element stretches to whatever the document already is and looks like the cause
when it is a victim. Hide subtrees and watch `scrollWidth`.

## Find the cause

Walk down from `body`, hiding one child at a time. The child whose removal drops
`scrollWidth` to the viewport owns the overflow. Descend into it and repeat.

```js
const W = document.documentElement.clientWidth;
const sw = () => document.documentElement.scrollWidth;
const name = el => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') +
  (typeof el.className === 'string' && el.className
    ? '.' + el.className.trim().split(/\s+/).join('.') : '');
const chain = []; let node = document.body;
for (let d = 0; d < 25; d++) {
  let found = null;
  for (const ch of Array.from(node.children)) {
    const p = ch.style.display; ch.style.display = 'none';
    const a = sw(); ch.style.display = p;
    if (a <= W) { found = ch; break; }
  }
  if (!found) break;
  chain.push(name(found)); node = found;
}
```

Two things about the answer:

- **The chain ends at a leaf; the cause is usually the row above it.** Letterrun's
  chain ended at a 176px `div.who`, and the fix was in the grid two levels up.
  Read the parent's `display`, `gridTemplateColumns`, `flex` and `minWidth`
  before touching the leaf.
- **An empty chain means several children share the blame.** No single one fixes
  it. Isolate each child in turn, showing only that one, and read its width.

## The four causes seen so far

| Shape | Reading | Fix |
| --- | --- | --- |
| Grid with no column track | `gridTemplateColumns` is a pixel value wider than the viewport | `grid-template-columns: minmax(0, 1fr)` |
| Flex item that will not shrink | `flex: 0 0 auto` or `min-width: auto` on a row that needs more than it has | `min-width: 0`, and `flex: 0 1 auto` on the item that should give |
| A toolbar with more controls than fit | items squeezed past their text, labels clipped | wrap it at a breakpoint and give one group its own line with `flex: 1 0 100%` and `order` |
| Content wider than any phone: a data table, a drawing | the content needs that width to be readable and should keep it | let it scroll inside its own `overflow-x: auto` container, and put `min-width: 0` on every ancestor between that container and the viewport, or the container is sized to its content and never scrolls |

A wrapping column flex container is a trap inside the last row: it sizes each
line to its widest item, so one wide table makes every sibling that wide. Add
`flex-wrap: nowrap` where the layout is a single column anyway.

## Stacking: two traps in the same breakpoint

A responsive block that sets `position: static` to put a floating element back
in the flow also throws away its `z-index`, because a static element has none.
On cutplan that dropped a palette and a panel behind the absolutely positioned
drawing that fills their container, and a tap at the centre of all seven tool
buttons landed on the drawing. `position: relative` rejoins the flow and keeps
the stacking. Check the z-index on an element and its siblings before changing
its `position` in a media query.

Prove it with `document.elementFromPoint` at the centre of every interactive
element, asserting the returned node is inside the control. A rectangle
intersection test between the two boxes you suspect is weaker: it passed on a
palette that had stopped covering the panel and was itself buried under a third
element the test never named.

## Prove the fix without breaking the desktop

Snapshot the geometry of the page's main boxes with the new CSS live in a
`<style>` element, then set `styleEl.disabled = true` and snapshot again. Compare
the two. An empty diff at 1440 is the evidence that a mobile fix changed nothing
above the breakpoint; do this before writing to the file, and say the box count
in the report.

Then measure every page in the tree, at both widths, with one iframe harness:
one page load, `scrolling="no"`, a fresh cache-busting `src` per page, and about
700ms after `onload` for scripts to draw. Validate the harness against a page
measured by direct navigation, one that passes and one that fails, before
trusting a batch of numbers from it.

## Before reporting

- Run the unit's own `build.py` and `test.js` if they exist. A CSS fix should
  leave both untouched; if the diff moves after a build, the build owns part of
  the file and the edit went in the wrong place.
- `git diff` and confirm no markup or script lines changed.
- Report the measured value for every page. The numbers are the finding, and a
  summary sentence hides which page still carries the defect.
