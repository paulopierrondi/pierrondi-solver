# PIERRONDI / LABS brand system

`PIERRONDI / LABS` is the maker signature behind Paulo Pierrondi's public
software portfolio. It is not a replacement for each product's identity. It is
the connective tissue that makes the portfolio feel authored by the same
builder.

## Brand thesis

> Build systems. Ship products. Show the proof.

The public promise is evidence, not spectacle:

- real software over vaporware;
- a working path over a concept deck;
- measurable outcomes over generic AI claims;
- transparent trade-offs over false certainty.

This extends the canonical Product lane in `pierrondi-brand-os`: *building real
products in public, with evidence over hype.*

## Brand architecture

| Layer | Name | Role |
| --- | --- | --- |
| Maker | `PIERRONDI / LABS` | Portfolio signature across GitHub and product building |
| Open source | `PIERRONDI / OPEN SOURCE LABS` | Editorial sign-off for public repositories |
| Product | `PIERRONDI / {PRODUCT}` | Product lockup when the maker relationship matters |
| Product brand | `{PRODUCT}` | Primary identity users should remember |

The product always leads. The maker signature should behave like a small
publisher's mark, not a corporate umbrella that flattens every product.

## Verbal identity

### Master line

`Build systems. Ship products. Show the proof.`

### Open-source line

`Open-source infrastructure for agents that need to keep moving.`

### Solver line

`Self-hosted challenge resolution for AI agents.`

### Voice

- Builder-first: explain what it does before explaining the vision.
- Precise: name the supported path, the fallback, and the limitation.
- Proof-led: use live demos, tests, commits, and observed metrics.
- Calmly technical: confident without cyberpunk or "AI revolution" clichés.
- Responsible: authorized automation only; never imply 2FA or login bypass.

### Preferred vocabulary

`local-first`, `agent-native`, `one HTTP API`, `provider cascade`,
`observable`, `authorized automation`, `real product`, `shipped`.

### Avoid

`magic`, `unbreakable`, `undetectable`, `bypass everything`, `human obsolete`,
invented benchmarks, unverifiable superlatives, and generic motivational copy.

## Visual system

### Core tokens

| Token | Value | Use |
| --- | --- | --- |
| `ink` | `#050706` | Primary dark canvas |
| `graphite` | `#111512` | Cards and secondary surfaces |
| `paper` | `#F4F7F2` | Primary type and light canvas |
| `steel` | `#8D968D` | Metadata and secondary copy |
| `line` | `#273026` | Grids and borders |
| `signal` | `#B7FF2A` | Solver accent and system-status emphasis |

`signal` belongs to the Solver and to small portfolio status cues. Other
products should select their own accent; the shared identity comes from
typography, spacing, grids, and the `P/` maker mark.

### Typography

- Display and UI: **Geist Sans**, with Arial/Helvetica fallback.
- Metadata and technical labels: **Geist Mono**, with Menlo/Consolas fallback.
- Display copy: uppercase only for short, high-impact statements.
- Metadata: wide tracking, compact size, restrained use.

### Graphic language

- Precision grids, thin telemetry paths, status nodes, and hard-edged rules.
- Mostly flat geometry with restrained depth.
- One signal color per product.
- Real product screenshots are the strongest proof asset.
- The `P/` mark identifies the maker; the gate mark identifies Solver.

### Composition

- 64 px base grid for wide assets; 8 px micro-grid for UI.
- Minimum clear space around any mark: one slash width.
- Keep the maker signature smaller than the product name.
- Use signal lime on no more than roughly 10% of a composition.
- Prefer a solid dark background for social previews across light/dark clients.

### Do not

- Recolor every product lime.
- place the maker mark larger than the product mark;
- use generic robot, brain, padlock, or glowing-orb imagery;
- add more than one accent color;
- put text inside AI-generated imagery;
- stretch, skew, outline, or add drop shadows to the marks.

## Product extension rule

Every product gets five decisions:

1. its own user promise;
2. one accent color;
3. one product mark;
4. one proof format (screenshot, metric, workflow, or demo);
5. one prohibited tone.

It inherits the grid, type system, metadata style, maker signature, and
evidence-first behavior. This preserves a recognizable portfolio without making
FaithSchool, CantuStudio, B2B automation products, and developer infrastructure
look interchangeable.

## Solver application

| Element | Decision |
| --- | --- |
| Product promise | Self-hosted challenge resolution for AI agents |
| Accent | Signal lime `#B7FF2A` |
| Mark | A signal crossing a verification gate |
| Proof | Live solve, latency/cost telemetry, test suite |
| Prohibited tone | Evasion, anti-ban, 2FA/login-bypass language |

## Asset map

All production assets live in [`../assets/brand`](../assets/brand):

- `pierrondi-labs-mark.svg` / `.png` — maker avatar;
- `pierrondi-labs-lockup.svg` — master lockup;
- `pierrondi-solver-mark.svg` / `.png` — product mark;
- `github-profile-banner.svg` / `.png` — profile README header;
- `github-social-preview.svg` — standalone vector preview;
- `github-social-preview.jpg` — 1280×640 upload-ready GitHub preview.

## GitHub rollout

1. Use the profile banner at the top of the `paulopierrondi/paulopierrondi`
   profile README.
2. Use the `P/` maker mark as the cross-product publisher signature.
3. Give every flagship repository a product-specific 1280×640 social preview.
4. Start every README with product promise, proof, quickstart, and limitations.
5. Use the community health files as a consistent trust layer.

Uploading the social preview, changing a public profile, or pushing these assets
is a separate public action and should happen only after explicit approval.
