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

## Geometric master

A geometric master should use circles and straight lines wherever supported, explicit shared
intersections where boundaries are intended to meet, and G1 circular transitions where the source
supports them. Duplicated positive/negative boundaries should share one geometric definition.

A source-local exception remains preferable when global normalization creates a topology defect.

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

Keep **v3** as the geometric master. Rebuild publication layering with oversized color underlays and use
the foreground construction to own the visible boundaries. Anyat is the first implementation target
because the Team Ops export provides useful independent first-party corroboration.

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
- the geometric master remains unchanged unless a separate evidence-backed geometry review changes it;
- local high-resolution review and normal UI-size review both pass.

## Generalization guardrail

Do not turn this model into an automatic transform for unrelated Infinity symbols. Another family must
first show compatible primitive geometry, boundary ownership, and layering semantics. Gradients, masks,
transparency, or intentionally independent outlines may require a different reconstruction model.
