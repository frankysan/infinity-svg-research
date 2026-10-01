# Morat unit symbols

Status: **active publication-topology migration**

Research topic: family-level geometric reconstruction and publication topology

## Scope

This case records the Morat unit-symbol work derived from the historical 24-unit corpus. The evidence
supports a shared circular design grammar across the family, but does not justify forcing every unit onto
one common set of internal centers or radii.

The publication-topology conclusions here are deliberately **Morat-family-specific**.

## Evidence hierarchy

Use evidence in this order:

1. exact or duplicated boundaries within the target first-party source;
2. shared circle families and continuity within that source;
3. recurring Morat-family scaffold evidence;
4. a corresponding newer first-party export when one exists;
5. raster metrics as validation and diagnostics, not authority over supported geometry.

Newer first-party Army SVGs are corroborating evidence, not automatic authority over local topology. The
Anyat/Team Ops comparison shows that later exports can preserve the large circle vocabulary while also
showing endpoint drift, oversimplification, collapsed micro-cuts, or other export damage. Use them to
confirm broad construction when appropriate, but re-derive fragile local geometry from the stronger
evidence above.

## Geometric master

A geometric master should use circles and straight lines wherever supported, explicit shared
intersections where boundaries are intended to meet, and G1 circular transitions where the source
supports them. Duplicated positive/negative boundaries should share one geometric definition.

A source-local exception remains preferable when global normalization creates a topology defect.

Classify local geometry explicitly:

- **canonical construction primitive** — a circle, line, intersection, or repeated family supported by
  independent source evidence;
- **supported local exception** — geometry that does not generalize but is still required by the source;
- **export/helper artifact** — tiny rounding circles, corrective slivers, drifted endpoints, or local
  bridge geometry that merely approximates a cleaner construction. These do not belong in the restored
  geometric master.

Before retaining two adjacent fitted circles, test whether the complete span is better explained by one
single circle. A small curvature bump at their join is evidence to investigate, not a reason to preserve
two primitives automatically.

## Publication topology

The preferred Morat publication representation follows the faction-symbol v10.1 model:

- one owner for each visible boundary;
- clean shared intersections instead of overlapping caps or blobs;
- oversized flat-color underlays behind foreground white/black construction;
- cutout-driven visible color islands;
- no subpixel seam dependence between neighboring colors;
- no nearly duplicated overlay paths when canonical geometry already defines the edge;
- no publication simplification that silently changes the geometric master.

## Migration plan

### Treitak Anyat

Status: **reference reconstruction complete**.

Use **v7** as the geometric master and **v7.3** as the restored-intent publication candidate. Anyat is the
first full reference implementation of the Morat-family method.

The decisive corrections were:

- remove small G1 fitting/helper circles that had no independent construction evidence and replace them
  with clean intersections of the supported larger circles;
- interpret the suspicious yellow corner as a drifted intersection. Re-fitting the nearby purple family
  through the clean yellow-circle intersection improved its old-source radial RMSE from about `0.0162` to
  `0.0100`;
- promote the yellow outer edge and the lower-right white boundary to the exact `r=33.6` inner ring where
  the source supports it;
- make the top and bottom black lobes actual cuts by the white `r=33.6` circle, removing the tiny
  exporter-rounding arcs rather than preserving them as design primitives;
- replace the remaining two-arc lower red boundary with one circle centered near
  `(47.990352, 17.569258)`, `r=48.369519`. Independent fits give about `0.0769` radial RMSE on the old
  Anyat source and `0.0728` on the newer Team Ops counterpart;
- keep the publication colors as oversized underlays exposed by canonical foreground cutouts. v7.3 adds
  a hidden `0.6` SVG-unit red overscan beneath the white cutout so antialiasing or minute coordinate drift
  cannot expose black at the red/white seam. The visible boundary is unchanged.

The modern Team Ops export remains useful corroboration for the broad circle language and smoothness, but
its small shapes are not treated as authoritative when older source geometry and clean intersections
provide a stronger explanation.

### Daturazi

Keep **v2** as the geometric master. Treat v2.1 as an intermediate micro-cleanup experiment. Preserve the
source-derived internal ring and rebuild color adjacency through foreground cutouts rather than seam
fragments.

### Suryats

Keep **v3** as the geometric master. Retain the promoted smooth circle families and canonicalize the slot
intersections in publication topology without forcing the genuinely compound lobes onto simpler circles.

### Rodok

Keep **v3** as the geometric master. Preserve the tiny explicit black correction in research; test whether
the underlay/cutout publication topology makes it redundant rather than regularizing or enlarging it.

### Zerat

Keep **v3** as the geometric master. Preserve the source-local upper-left junction in research. Rebuild
the surrounding color fields so the old v2 white-pinhole failure cannot recur.

### Yaogat

Keep **v2** as the geometric master. Treat v2.1 as an intermediate cleanup experiment. Rebuild the dense
central color topology with underlays and determine whether the seven brown correction paths disappear
naturally once shared boundaries have one owner.

## Acceptance criteria

A Morat unit publication candidate is ready only when:

- intended intersections are clean at high magnification;
- no visible gaps remain between color blocks;
- one visible boundary is not approximated independently by multiple near-identical paths;
- no blob, beak, pinhole, or seam patch remains solely because paths failed to share topology;
- hidden color underlays extend far enough beneath authoritative foreground cutouts that background color
  cannot leak through at antialiased borders;
- the geometric master remains unchanged unless a separate evidence-backed geometry review changes it;
- local high-resolution review and normal UI-size review both pass.

## Generalization guardrail

Do not turn this model into an automatic transform for unrelated Infinity symbols. Another family must
first show compatible primitive geometry, boundary ownership, and layering semantics. Gradients, masks,
transparency, or intentionally independent outlines may require a different reconstruction model.
