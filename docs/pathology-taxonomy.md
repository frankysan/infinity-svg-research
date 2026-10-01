# SVG pathology taxonomy

The scanner distinguishes **hard classifications** from **advisories**. Hard classifications represent
specific structural patterns with enough evidence to call the export pathological. Advisories identify
unusual properties worth inspection but are not proof of a defect.

## Hard classifications

### `duplicate-fill-stroke-geometry`

Large systematic duplication where matching geometry is emitted separately for fill and stroke. The
exact optimizer gate requires at least 8 matching pairs and at least 4,000 duplicated path-data bytes.
An isolated pair is not sufficient.

### `embedded-raster-heavy`

A large fraction of an SVG consists of embedded raster images even though the visible effect appears to
be a candidate for vector/filter reconstruction. Detection does not imply that replacement is safe.

### `flattened-blend-stack`

Repeated near-identical geometry represents a blend/interpolation that could be encoded as a reusable
base shape plus transforms/uses rather than hundreds of generated objects.

### `flattened-gradient-mask`

A gradient/mask appearance is flattened into many repeated circles/strips plus embedded raster masks,
filters, and duplicated gradient definitions. Current known examples share a circular badge scaffold.

### `micro-contour-explosion`

Compound paths contain very large numbers of tiny closed contours that contribute little or nothing at
normal rendering sizes. This differs from legitimate detailed lettering merely being subpixel at small
sizes.

### `off-artboard-content`

Large top-level graphic branches are provably wholly outside the SVG viewBox. Removal is exact only when
references/dependencies are also handled conservatively.

### `palette-fragmented-trace`

A traced image encodes intended flat regions as many near-colours and fragmented boundaries. Palette
snapping alone does not repair the underlying geometry.

## Advisories

### `large-path-payload`

A path consumes unusually large serialized geometry. This is a review signal, not evidence that the path
is redundant.

### `missing-external-image`

An SVG references a sidecar image that was not acquired. It may be invisible/covered or may be required;
visibility must be tested.

### `palette-fragmentation`

The colour distribution resembles a traced/fragmented palette but does not meet the hard-classification
threshold.

### `subpixel-detail-heavy`

A large share of closed detail is subpixel at common display sizes. This can be legitimate typography or
linework and is not automatically removable.
