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
  `5.67` apart;
- a second upper circular band centered at approximately `(50.088029, 87.919398)`, with radii
  `51.718624` and `46.048624` in the current normalized construction.

The second upper band was initially treated as a single-export hypothesis. Follow-up v7 analysis found
that it is repeated independently across several positive and negative source regions, not just one fitted
boundary. The outer family occurs in both the compound white path and the large black region. The inner
family occurs in the compound white path and three separate black regions, including several disjoint arc
intervals.

An unconstrained concentric fit to unique source segments recovers a secondary-band width of about
`5.8039`. Constraining it to the already established `5.67` width raises joint radial RMSE only from about
`0.1527` to `0.1590` SVG units. The long band independently recovers about `5.6158`, with RMSE moving from
about `0.0478` to `0.0519` when constrained to `5.67`. These small penalties support a shared nominal
width with exporter drift rather than unrelated free-form curves.

The secondary band is therefore **source-supported within the current first-party export**. Cross-source
historical confirmation would still be useful, but is no longer required to retain the circular-band
model as the preferred reconstruction hypothesis.

## Red regions

The v6 experiment removed the remaining hand-fitted red field as an independent construction. The three
substantive red islands in the raw export are each bounded by the same recovered ribbon-edge circles:

- region 1: path5 inner edge, path7 inner edge, path8 inner edge;
- region 2: path7 inner edge, path9 inner edge, path5 inner edge, path8 outer edge;
- region 3: path9 outer edge, path7 inner edge, path3 inner edge, path5 inner edge.

The raw cubic boundaries follow those assigned circles with roughly `0.07` to `0.40` SVG-unit radial RMSE,
and the raw vertices lie roughly `0.09` to `0.52` units from the corresponding exact pairwise circle
intersections. That is consistent with the same export drift already observed elsewhere in the symbol.

A microscopic red sliver around `(42.6, 42.6)` is not promoted to authored geometry. It remains classified
as an overlap/export-artifact candidate.

## Endpoint topology

Most ribbon endpoints are now explained by circle intersections. The v7 experiment adds two more supported
rules without changing the visible design materially:

- path8 end is the direct intersection of its centerline circle with the established upper long-band inner
  circle, giving approximately `(56.239966, 37.271308)`;
- path9 end is a radial cap derived from the intersection of its outer edge circle with the upper secondary
  outer circle, giving centerline endpoint approximately `(68.834218, 41.033681)`.

The path5 and path7 starts remain source-fitted hidden caps. Stronger-looking normalizations were tested
and rejected rather than forced. In particular, moving the path7 start to the exact intersection implied
by its outer edge and the secondary inner circle materially worsened the localized source comparison. A
cardinal-top normalization also slightly worsened the source fit. Since the cap is buried by adjoining
white geometry, retaining the source-supported endpoint is preferable to inventing a cleaner rule.

Numeric evidence is recorded in
[`../../reports/morat-geometric-v6.json`](../../reports/morat-geometric-v6.json) and
[`../../reports/morat-geometric-v7.json`](../../reports/morat-geometric-v7.json). Source and candidate
artwork remain outside Git under the repository's provenance/licensing policy.

## Guardrails

- Do not force circular geometry merely because it is aesthetically cleaner.
- Treat project-authored redraw geometry as a hypothesis, not source authority.
- Preserve deliberate asymmetry if the source supports it.
- Prefer a small shared construction over independently tuned Béziers only when the residuals and visual
  evidence justify it.
- Treat endpoint rules independently from circle-family recovery: a well-supported circle does not prove
  that every hidden cap should be snapped to the nearest mathematically convenient intersection.

## Next step

The main unresolved Morat work is now the small number of retained connector/cap choices rather than the
circle families or red field. Continue only where a new constraint is supported by source topology. Avoid
further global fitting that merely lowers pixel RMSE against exporter drift.
