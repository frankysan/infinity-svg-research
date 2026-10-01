# Provenance policy

## Purpose

Reconstruction decisions must be traceable to source evidence. Provenance establishes **where evidence
came from**; it does not by itself determine how useful a source is for a particular question.

The project uses two source-authority classes:

1. **first-party** — material published by Corvus Belli;
2. **second-party** — non-Corvus-Belli reference material used to corroborate, recover, or interpret the
   artwork.

Within each class, record the representation type, resolution/quality, date or snapshot when known, and
how the source was used.

## First-party sources

First-party evidence is the primary authority for authorial intent.

Included sources are:

- **Infinity Army SVG files** obtained from official Corvus Belli asset infrastructure;
- **vector artwork from Corvus Belli websites**, including downloadable or embedded vector assets;
- **vector artwork recovered from Corvus Belli PDF documents** when the PDF contains native vector
  content rather than only a raster image;
- **bitmap images published by Corvus Belli**, including website imagery and raster artwork extracted
  from official PDF documents.

First-party vector sources are normally the strongest geometry evidence because they preserve paths,
shapes, gradients, and relative placement directly. First-party bitmaps remain authoritative visual
evidence and can be more useful than a pathological vector export when determining intended appearance.

Current and historical first-party sources should be distinguished. A historical official asset can be
valuable evidence for a design that was later exported poorly, but it must not silently override an
intentional later redesign.

## Second-party sources

Second-party sources are supporting evidence rather than the primary authority.

Included sources are:

- **Human Sphere PNG renders**, especially where they preserve a clear rendering of an official asset or
  an earlier visual state;
- **high-quality fan-made SVGs** that provide useful vector interpretation or reconstruction evidence.

Second-party material may be used to:

- corroborate the appearance of first-party artwork;
- identify details obscured by a damaged or pathological first-party export;
- suggest a plausible vector construction to test against first-party evidence;
- provide a visual guardrail when the available first-party source is low-resolution or incomplete.

Second-party material must not silently become the authoritative source. Fan-made geometry must remain
identified as fan-made even when it is technically cleaner than available first-party assets. Human
Sphere renders should be treated as evidence of appearance, not proof of underlying vector geometry.

## Project-authored reconstructions

Manual redraws, generated candidates, fitted primitives, and other reconstructions produced within this
project are **research artifacts**, not a third source-authority class. They do not become evidence of
Corvus Belli's intent merely because they are clean or geometrically convincing.

Such artifacts may be used to:

- demonstrate a reconstruction method;
- test a geometric hypothesis against first- or second-party evidence;
- serve as regression/reference examples for tooling;
- document accepted project conventions such as concentric geometry or rotational repetition.

When a project-authored redraw influences a later reconstruction, cite the underlying first-/second-party
evidence and the reconstruction decision separately. Do not cite the redraw itself as independent
provenance.

The manually reconstructed Combined Army, Morat, Onyx, Shasvastii, and Exrah examples are therefore
methodological references for geometric construction recovery, not provenance sources. See
[`geometric-reconstruction.md`](geometric-reconstruction.md).

## Evidence ordering

When sources disagree, prefer evidence in this order unless the case record documents a reason to do
otherwise:

1. current first-party vector material that clearly represents the intended artwork;
2. other first-party vector material, including vectors from official websites or PDFs;
3. first-party bitmap material;
4. second-party renders that can be tied convincingly to the artwork under investigation;
5. high-quality fan-made vectors and other second-party reconstructions.

This ordering is a default, not a mechanical rule. A visibly pathological current Army SVG may be weaker
appearance evidence than an official bitmap of the same design. The case record should explain such
exceptions explicitly.

## Provenance versus representation quality

Keep **authority** and **representation quality** separate.

For example:

- an official 128 px PNG is first-party but low-resolution;
- a fan-created SVG may be high-resolution vector evidence but remains second-party;
- an Army SVG can be first-party and vector-based while still containing exporter pathology.

This distinction prevents a technically convenient source from being mistaken for a more authoritative
one.

## Required provenance record

For every source used materially in a reconstruction, record when available:

- source authority: `first-party` or `second-party`;
- source type, such as `army-svg`, `official-web-vector`, `official-pdf-vector`, `official-bitmap`,
  `human-sphere-render`, or `fan-vector`;
- source URL or document identity;
- local/snapshot identity where applicable;
- acquisition date or snapshot date when known;
- SHA-256 and byte size for acquired files;
- dimensions for bitmap material;
- whether the source is current or historical;
- the role it played: primary geometry, appearance reference, corroboration, or guardrail;
- any uncertainty about attribution or relationship to the target artwork.

Raw source assets remain outside this Git repository. The repository stores source identities, hashes,
metadata, methodology, and compact research conclusions needed to reproduce the reasoning.

## Generated candidates

Generated SVGs, comparison PNGs, and full run manifests are experiment outputs and are not committed by
default. Compact summaries containing hashes, metrics, provenance, and decisions belong under
`research/reports/`.
