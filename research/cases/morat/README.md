# Morat

Status: **resolved reconstruction**

Research topic: geometric construction recovery

## Motivation

A project-authored manual redraw demonstrated the intended reconstruction mindset but is not itself
provenance evidence. The redraw regularized the outer badge as exact concentric circles while leaving
several internal ribbon-like forms as eyeballed Bézier curves. The v6-v9 research recovered those
regions as a compact circle/arc construction, and v10 performed a cleanup-only topology pass without
changing that recovered geometry.

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

The v8 review resolves the path5 start as well. In v7, the upper-secondary inner boundary and path5
outer edge ended on separate caps, producing a visible black "beak" at the left junction. Extending the
two already recovered circles gives a single shared apex at approximately `(31.929551, 45.602198)`. The
path5 centerline start is the radial projection of that apex back to the path5 centerline, approximately
`(34.599887, 44.650081)`.

This is both structurally cleaner and better supported by the source render. At 1600 px, the local apex
crop improves from about `36.36` to `31.32` RGBA RMSE against the raw source, and a tighter crop improves
from about `44.87` to `35.67`. The full-image RMSE also improves slightly. The v7 beak is therefore treated
as a reconstruction artifact caused by independent cap endpoints, not as authored geometry.

The v9 review refines the path5 outer start again. The v8 shared-apex correction removed the visible
beak, but it did so by inserting a short straight bridge between the upper-band point and the path5
outer circle. The first-party source has duplicate forward/reverse cubic boundaries beginning directly
at about `(29.4, 40.5)` and continuing as one curve, so that straight bridge is not source-supported.

The source boundary converges rapidly onto the established path5 outer circle. A second large-radius
circle through the upper-band point can be joined tangentially to the path5 outer circle after roughly
30% of the raw cubic. The resulting two-circle boundary is G1-continuous at the join. Its geometric RMSE
against the raw cubic is about `0.060` SVG units, compared with about `0.250` for treating the whole
boundary as the original path5 outer circle. At 1600 px, the tight junction crop improves by about
13.45% against the raw render and the full-image RMSE also improves slightly.

A whole-boundary low-eccentricity ellipse was tested as an alternative. It improves the isolated outer
boundary fit, but moving the complete stroked ribbon onto that ellipse damages the already-good inner and
downstream geometry. The smaller two-circle transition is therefore preferred: it changes only the
source-supported exceptional start and rejoins the established circular family tangentially.

The path7 start remains source-fitted. Its previously tested exact-intersection and cardinal-top
normalizations remain rejected because they worsen the localized source comparison.

## Final representation decision

The reconstruction now has deliberately different research and publication representations:

- **v9 is the geometric research master.** It retains the recovered primitive construction explicitly:
  concentric badge circles, circular ribbon families, shared-width bands, circle intersections, and the
  local G1-continuous two-circle transition at the path5 start.
- **v10 established the first cleaned publication candidate.** It froze the v9 geometry, boolean-unioned
  contiguous white regions, and removed four non-authorial micro-holes caused by adjacent fill/stroke
  topology.
- **v10.1 is the preferred publication model.** A manual topology pass kept the recovered geometry but
  replaced separately authored visible red islands with one oversized red underlay revealed through the
  foreground white construction. It also removed a redundant lower-left black corrective overlay whose
  visible edge was already defined by the canonical foreground topology.

At 1600 px, v10 and v10.1 differ by about `0.94` RGBA RMSE and only about `0.106%` of pixels differ by
more than one channel value. Full-image raw-source RMSE changes only from about `22.4948` to `22.5029`.
The simpler topology is preferred because shared boundaries have one owner rather than several nearly
coincident paths.

This split is intentional. The research master preserves the recovered construction for inspection and
future evidence review, while publication topology may simplify layering, boolean structure, and
antialiasing without silently redefining supported geometry.

Numeric evidence is recorded in
[`../../reports/morat-geometric-v6.json`](../../reports/morat-geometric-v6.json),
[`../../reports/morat-geometric-v7.json`](../../reports/morat-geometric-v7.json),
[`../../reports/morat-geometric-v8.json`](../../reports/morat-geometric-v8.json),
[`../../reports/morat-geometric-v9.json`](../../reports/morat-geometric-v9.json),
[`../../reports/morat-geometric-v10.json`](../../reports/morat-geometric-v10.json), and
[`../../reports/morat-publication-v10.1.json`](../../reports/morat-publication-v10.1.json). Source and
candidate artwork remain outside Git under the repository's provenance/licensing policy.

## Morat-family publication-topology lesson

v10.1 establishes the preferred publication model for the Morat family:

- foreground circle/line geometry owns visible boundaries;
- intended intersections meet at explicit shared points rather than overlapping into blobs;
- oversized flat-color underlays extend safely behind foreground geometry;
- foreground cutouts reveal the intended color islands;
- neighboring color regions do not depend on subpixel-perfect coincidence to avoid gaps;
- redundant overlays and seam-fixing fragments are removed when canonical geometry already provides the
  intended edge.

This is a Morat-family conclusion only. It must not be generalized to unrelated Infinity symbol families
without separate evidence.

## Guardrails

- Do not force circular geometry merely because it is aesthetically cleaner.
- Treat project-authored redraw geometry as a hypothesis, not source authority.
- Preserve deliberate asymmetry if the source supports it.
- Prefer a small shared construction over independently tuned Béziers only when the residuals and visual
  evidence justify it.
- Treat endpoint rules independently from circle-family recovery.
- Keep geometric recovery separate from publication topology: an oversized underlay is a rendering
  simplification, not evidence for a different circle, radius, intersection, or tangent rule.

## Closure and revisit criteria

The Morat geometric reconstruction is considered complete. The path7 start remains source-fitted because
previous exact-intersection and cardinal-top alternatives worsened the localized source comparison.

Reopen the geometry only for a specific visual defect, materially stronger first-party evidence, or a
new construction constraint supported by source topology. Do not resume global fitting merely to lower
pixel RMSE against exporter drift. Downstream publication work should use the v10.1 underlay/cutout
representation while retaining v9 as the geometric research master.
