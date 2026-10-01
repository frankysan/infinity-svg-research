# Vyo SVG archive inventory v1

- SVG files: **565**; parse errors: **0**; exact duplicate groups: **1**.
- Document setup: **545** files use `8.5in × 11in`, `viewBox="0 0 8500 11000"`; **20** use `215.9mm × 279.4mm`, `viewBox="0 0 21590 27940"`.
- ZIP timestamps span **2015–2022**; the N4-style group is concentrated in 2021, plus Wild Bill in 2022.
- Structural exceptions: **1** image/clip-path SVG, **20** text SVGs, **4** gradient SVGs, **39** SVGs with transforms. All 565 parse as XML.
- Current InfinityDB manifest (2026-09-29 Army snapshot): **808 canonical assets**, including **740 canonical unit source paths**, **60 faction mappings**, and **9 static mappings**.
- Conservative name matching finds **362** high-confidence matches among ~708 normalized current unit subjects, **7** ambiguous matches, and **339** likely gaps. This deliberately undercounts Vyo coverage because semantic renames and spelling changes produce false negatives.

## Important interpretation

The low-ID/legacy false negatives are highly informative: most are simple renames or equivalent symbols (Joan/Jeanne d'Arc, Ahl Fassed/Al-Fasid, Die/Der Morlock Gruppe, Noctifier/Noctifers, Treitak Spec-Ops/Anyat, etc.). After resolving those obvious cases, Vyo's N3-era coverage appears close to comprehensive. Most of the large current gap is therefore **post-Vyo material**, not unfinished N3 work.

## Historical archive-name gaps worth checking first

- `fusilier-indigo-bipandra` — **confirmed_archive_name_gap**: No Vyo file containing Bipandra.
- `indigo-brother-konstantinos` — **confirmed_archive_name_gap**: No Vyo file containing Konstantinos.
- `volunteer-intel-isobel-mcgregor` — **confirmed_archive_name_gap**: No Vyo file containing Isobel.
- `zamira-nazarova` — **confirmed_archive_name_gap**: No Vyo file containing Zamira.
- `cassandra-kusanagi` — **confirmed_archive_name_gap**: No Vyo file containing Kusanagi.
- `neema-saatar` — **confirmed_archive_name_gap**: No Vyo file containing Neema.
- `hatail-aelis-keesan` — **needs_visual_identity_check**: No Aelis file; Vyo has Hatail Spec-Ops, which may or may not share the same emblem.
- `scarface-and-cordelia` — **composition_check**: Vyo has separate Scarface Turner and Cordelia Turner assets; current combined asset may need composition rather than new geometry.

## Reuse blockers / exceptions

- `Mercs - Armand Le Muet Freelance Killer` embeds a PNG and uses a clip path: this is not a clean vector base and is a strong reconstruction target.
- The 20 text-bearing SVGs depend on fonts; these need text-to-path conversion or a documented font-resolution stage before publication.
- Four files use gradients (Valkyrie logo/name, Nomads Moderators, Mercs Cypher). Review whether gradients are intentional design or publication baggage before flattening.
- The fixed physical sizes and page viewBoxes are corpus-wide metadata issues and can be normalized mechanically, but artwork placement is not uniform: many older badge files are centered at `(0,11000)`, others at `(3937,7063)`, while the N4 group uses `(10000,17940)`. Do not replace every viewBox with one hard-coded rectangle; derive it from the badge/construction bounds or drawing bounds.

## Recommended project direction

1. Treat Vyo as the preferred starting geometry when a matching symbol exists and passes structural/visual review.
2. Normalize document metadata separately from geometry.
3. Build an explicit Vyo ↔ Army identity map so semantic renames do not look like missing assets.
4. Spend reconstruction effort on current Army symbols with no Vyo identity, plus the small set of Vyo structural exceptions.
