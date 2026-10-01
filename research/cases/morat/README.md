# Morat

Status: **active research**

Research topic: geometric construction recovery

## Motivation

A project-authored manual redraw demonstrates the intended reconstruction mindset but is not itself
provenance evidence. The redraw regularizes the outer badge as exact concentric circles. Its internal
ribbon-like forms were still based on eyeballed Bézier curves, so Morat remains an explicit research
subject rather than a finished reference reconstruction.

## Recovered construction

The current evidence supports a substantially smaller geometric system than the original exported paths:

- badge center `(56.7, 56.7)` with radii `56.7`, `41.1`, and `33.48`;
- a common internal ribbon width of `5.67`, exactly `113.4 / 20`;
- six internal ribbon centerlines that are well explained by circular arcs rather than free-form curves;
- a lower-left black negative region derived from the inner badge circle plus already recovered ribbon
  edge circles;
- an upper long-sweep band centered at `(25.6, 107.4)` with radii `82.2` and `76.53`, again exactly
  `5.67` apart.

The compound upper sweep also has a strong second constant-width fit centered at approximately
`(50.088029, 87.919398)`, with radii `51.718624` and `46.048624`. Its joint radial RMSE is about `0.173`
SVG units. This materially improves the source fit, but it is still classified as a **strong single-export
hypothesis** because no independent historical/first-party Morat SVG instance has yet been recovered to
confirm it.

## Red regions

The v6 experiment removes the remaining hand-fitted red field as an independent construction. The three
substantive red islands in the raw export are each bounded by the same recovered ribbon-edge circles:

- region 1: path5 inner edge, path7 inner edge, path8 inner edge;
- region 2: path7 inner edge, path9 inner edge, path5 inner edge, path8 outer edge;
- region 3: path9 outer edge, path7 inner edge, path3 inner edge, path5 inner edge.

The raw cubic boundaries follow those assigned circles with roughly `0.07` to `0.40` SVG-unit radial RMSE,
and the raw vertices lie roughly `0.09` to `0.52` units from the corresponding exact pairwise circle
intersections. That is consistent with the same export drift already observed elsewhere in the symbol.

A microscopic red sliver around `(42.6, 42.6)` is not promoted to authored geometry. It is currently
classified as an overlap/export-artifact candidate.

Numeric evidence for this experiment is recorded in
[`../../reports/morat-geometric-v6.json`](../../reports/morat-geometric-v6.json). Source and candidate
artwork remain outside Git under the repository's provenance/licensing policy.

## Guardrails

- Do not force circular geometry merely because it is aesthetically cleaner.
- Treat project-authored redraw geometry as a hypothesis, not source authority.
- Preserve deliberate asymmetry if the source supports it.
- Prefer a small shared construction over independently tuned Béziers only when the residuals and visual
  evidence justify it.
- Do not promote the secondary upper band to canonical geometry until independent source evidence exists
  or the remaining uncertainty is otherwise resolved explicitly.

## Next step

The main unresolved construction question is now the secondary upper band, not the red field. Search for
an independent first-party/historical Morat instance and test the same center/radii there. If none can be
recovered, continue endpoint/tangency analysis while keeping the band marked provisional rather than
optimizing it against one export.
