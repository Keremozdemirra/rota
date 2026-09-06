# Design references

Bookmarks, not installs. Collected 2026-08-31 for the personal site
(`keremozdemir.de`) — the one project here with a visual surface.

Nothing on this list is a tool to add to the setup. The design *capability*
is already covered by `design-taste-frontend`, `de-ai-slop-ui`,
`emil-design-eng`, the `impeccable` plugin and `artifact-design`. What was
missing is reference material, which is what these are.

## Galleries and inspiration

| Site | What it is |
|---|---|
| refero.design | Screenshots of real shipped product UI, searchable by pattern |
| 60fps.design | Motion and interaction reference, recorded from real apps |
| uiverse.io | Community CSS components, single-effect scale |
| paidax01.github.io/math-curve-loaders | Loading animations from classical curves — rose, Lissajous, hypotrochoid, cardioid, Cassini oval, Archimedean spiral, lemniscate, butterfly. **Look, do not copy: the repository carries no licence at all**, so the "copyable snippets" are all-rights-reserved. The mathematics is public domain; the implementation is not. If one of these is wanted, `animate` can write it from the parameterisation. |

## Component sources

| Site | What it is | Caution |
|---|---|---|
| reactbits.dev | React animated components, copy-paste | — |
| componentry.dev | Component documentation | — |
| Jakubantalik/Libraries · MIT · 2.7k ★ | Border beam, liquid gooey, thinking orbs; web editor at gooey.jakubantalik.com | — |
| vengenceui.com | 46 components, 100+ landing blocks | **The domain is a misspelling of the product name** — the source that forwarded it said so explicitly. Whatever the intent, a component library on a deliberately misspelled domain is not somewhere to run an install command from. Read the code, copy what you want by hand, install nothing. |

## Libraries (not agent tools)

- **chenglou/pretext** · MIT · 50.1k ★ — text measurement and layout for JS.
  Relevant only when typography needs measuring at runtime; it is a
  dependency for an application, not something the agent setup installs.

## Reading

- omersaidakcin.com/kullanici-neden-30-saniyede-siliyor — Turkish, on why
  users delete an app within 30 seconds. Onboarding and first-run, which is
  the weakest part of most portfolio sites.
