from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np
from lxml import etree
from PIL import Image

from infinity_svg_research import blend_use_reconstruct
from infinity_svg_research import micro_contour_prune
from infinity_svg_research import gradient_mask_reconstruct
from infinity_svg_research import gradient_mask_model
from infinity_svg_research import gradient_mask_batch
from infinity_svg_research import scan


class MicroContourPruneTests(unittest.TestCase):
    def test_prunes_tiny_absolute_closed_subpath(self) -> None:
        path_data = "M0 0 L10 0 L10 10 Z M20 20 l0.01 0 l0 0.01 z"
        candidate, stats = micro_contour_prune.prune_path_data(path_data, max_span=0.1)
        self.assertEqual(stats["removed_subpaths"], 1)
        self.assertIn("M0 0", candidate)
        self.assertNotIn("M20 20", candidate)

    def test_prunes_later_relative_moveto_safely(self) -> None:
        path_data = "M0 0 L10 0 Z m20 20 l0.01 0 l0 0.01 z"
        candidate, stats = micro_contour_prune.prune_path_data(path_data, max_span=0.1)
        self.assertEqual(stats["removed_subpaths"], 1)
        self.assertEqual(candidate, "M0 0 L10 0 Z")

    def test_rebases_retained_relative_moveto_after_removed_subpath(self) -> None:
        path_data = "M10 10 l0.01 0 l0 0.01 z m20 20 l10 0 l0 10 z"
        candidate, stats = micro_contour_prune.prune_path_data(path_data, max_span=0.1)
        self.assertEqual(stats["removed_subpaths"], 1)
        self.assertEqual(stats["rebased_relative_movetos"], 1)
        self.assertEqual(candidate, "M30 30 L40 30 L40 40 Z")

    def test_relative_moveto_uses_closed_subpath_start_as_current_point(self) -> None:
        path_data = "M10 10 l10 0 l0 10 z m5 5 l10 0 l0 10 z"
        candidate, stats = micro_contour_prune.prune_path_data(path_data, max_span=0.0)
        self.assertEqual(candidate, path_data)
        self.assertEqual(stats["removed_subpaths"], 0)

    def test_rebase_preserves_implicit_relative_lineto_pairs(self) -> None:
        path_data = "M0 0 l0.01 0 l0 0.01 z m20 20 10 0 0 10 z"
        candidate, stats = micro_contour_prune.prune_path_data(path_data, max_span=0.1)
        self.assertEqual(stats["removed_subpaths"], 1)
        self.assertEqual(candidate, "M20 20 L30 20 L30 30 Z")


class BlendUseReconstructTests(unittest.TestCase):
    def _source(self) -> bytes:
        svg = etree.Element(f"{{{scan.SVG}}}svg", nsmap={None: scan.SVG, "xlink": scan.XLINK})
        defs = etree.SubElement(svg, f"{{{scan.SVG}}}defs")
        style = etree.SubElement(svg, f"{{{scan.SVG}}}style")
        rules = []
        stack = etree.SubElement(svg, f"{{{scan.SVG}}}g")
        for step_index in range(20):
            step = etree.SubElement(stack, f"{{{scan.SVG}}}g")
            for glyph_index in range(2):
                gradient_id = f"g-{step_index}-{glyph_index}"
                gradient = etree.SubElement(
                    defs,
                    f"{{{scan.SVG}}}linearGradient",
                    id=gradient_id,
                    x1="0",
                    y1="0",
                    x2="10",
                    y2="0",
                    gradientUnits="userSpaceOnUse",
                    gradientTransform=f"translate({step_index} 0)",
                )
                etree.SubElement(gradient, f"{{{scan.SVG}}}stop", offset="0", **{"stop-color": "#000000"})
                etree.SubElement(gradient, f"{{{scan.SVG}}}stop", offset="1", **{"stop-color": "#ffffff"})
                class_name = f"s-{step_index}-{glyph_index}"
                rules.append(f".{class_name}{{fill:url(#{gradient_id})}}")
                x = step_index + glyph_index * 3
                etree.SubElement(
                    step,
                    f"{{{scan.SVG}}}path",
                    attrib={"class": class_name, "d": f"M{x},0 l1,0 l0,1 z"},
                )
        style.text = "".join(rules)
        return etree.tostring(svg, encoding="UTF-8", xml_declaration=True)

    def test_rewrites_confirmed_stack_and_prunes_gradients(self) -> None:
        root = etree.fromstring(self._source())
        tree = etree.ElementTree(root)
        rewrite = blend_use_reconstruct.rewrite_blend_stacks(tree)
        self.assertEqual(rewrite["rewritten_stacks"], 1)
        self.assertEqual(rewrite["generated_uses"], 19)
        css = blend_use_reconstruct.prune_unused_class_rules(root)
        gradients = blend_use_reconstruct.prune_unused_gradients(root)
        self.assertEqual(css["removed_css_rules"], 38)
        self.assertEqual(gradients["removed_gradients"], 38)
        self.assertEqual(len(root.xpath(".//s:use", namespaces=scan.NS)), 19)
        self.assertEqual(len(root.xpath(".//s:linearGradient", namespaces=scan.NS)), 2)


class GradientMaskReconstructTests(unittest.TestCase):
    def _source(self) -> bytes:
        svg = etree.Element(f"{{{scan.SVG}}}svg", nsmap={None: scan.SVG, "xlink": scan.XLINK})
        svg.set("viewBox", "0 0 82.2 82.2")
        defs = etree.SubElement(svg, f"{{{scan.SVG}}}defs")
        base_gradient = etree.SubElement(
            defs,
            f"{{{scan.SVG}}}linearGradient",
            id="orange-base",
            x1="0",
            y1="0",
            x2="1",
            y2="0",
            gradientUnits="userSpaceOnUse",
        )
        etree.SubElement(base_gradient, f"{{{scan.SVG}}}stop", offset="0", **{"stop-color": "#ffb669"})
        etree.SubElement(base_gradient, f"{{{scan.SVG}}}stop", offset="1", **{"stop-color": "#ff6b00"})
        for index in range(44):
            gradient = etree.SubElement(defs, f"{{{scan.SVG}}}linearGradient", id=f"orange-{index}")
            gradient.set(f"{{{scan.XLINK}}}href", "#orange-base")
        filter_node = etree.SubElement(defs, f"{{{scan.SVG}}}filter", id="mask-filter")
        etree.SubElement(filter_node, f"{{{scan.SVG}}}feColorMatrix")
        mask = etree.SubElement(defs, f"{{{scan.SVG}}}mask", id="ring-mask")
        etree.SubElement(mask, f"{{{scan.SVG}}}image", href="data:image/png;base64,AAAA")
        outer_clip = etree.SubElement(defs, f"{{{scan.SVG}}}clipPath", id="outer-clip")
        etree.SubElement(outer_clip, f"{{{scan.SVG}}}circle", cx="41.1", cy="41.1", r="32.02")
        inner_clip = etree.SubElement(defs, f"{{{scan.SVG}}}clipPath", id="inner-clip")
        etree.SubElement(inner_clip, f"{{{scan.SVG}}}circle", cx="41.1", cy="41.1", r="24.69")
        style = etree.SubElement(defs, f"{{{scan.SVG}}}style")
        style.text = ".foreground{fill:#fff}.unused{fill:#000}"

        isolation = etree.SubElement(svg, f"{{{scan.SVG}}}g", style="isolation:isolate")
        layer = etree.SubElement(isolation, f"{{{scan.SVG}}}g", id="layer")
        etree.SubElement(layer, f"{{{scan.SVG}}}path", d="M0 0h82.2v82.2z", fill="#9c9b9b")
        outer_stripes = etree.SubElement(layer, f"{{{scan.SVG}}}g", style="clip-path:url(#outer-clip)")
        for index in range(20):
            etree.SubElement(outer_stripes, f"{{{scan.SVG}}}path", d=f"M0 {index}h82")
        masked = etree.SubElement(layer, f"{{{scan.SVG}}}g", style="mask:url(#ring-mask)")
        etree.SubElement(masked, f"{{{scan.SVG}}}circle", cx="41.1", cy="41.1", r="32.02", fill="#040505")
        multiply = etree.SubElement(layer, f"{{{scan.SVG}}}g", style="mix-blend-mode:multiply")
        for index in range(44):
            etree.SubElement(
                multiply,
                f"{{{scan.SVG}}}circle",
                cx="41.1",
                cy="41.1",
                r="24.69",
                fill=f"url(#orange-{index})",
            )
        etree.SubElement(layer, f"{{{scan.SVG}}}circle", cx="41.1", cy="41.1", r="24.69", fill="url(#orange-base)")
        inner_stripes = etree.SubElement(layer, f"{{{scan.SVG}}}g", style="clip-path:url(#inner-clip)")
        for index in range(38):
            etree.SubElement(inner_stripes, f"{{{scan.SVG}}}path", d=f"M{index} 0l20 20")
        etree.SubElement(layer, f"{{{scan.SVG}}}path", d="M10 10h5v5z", attrib={"class": "foreground"})
        return etree.tostring(svg, encoding="UTF-8", xml_declaration=True)

    def test_reconstructs_guijia_style_scaffold(self) -> None:
        root = etree.fromstring(self._source())
        tree = etree.ElementTree(root)
        result = gradient_mask_reconstruct.reconstruct_tree(tree)
        self.assertEqual(result["outer_stripe_paths_removed"], 20)
        self.assertEqual(result["inner_stripe_paths_removed"], 38)
        self.assertEqual(result["multiply_circles_removed"], 44)
        self.assertEqual(result["gradient_count"], 3)
        self.assertEqual(result["accent_base_gradient"]["coordinates"], {
            "x1": "21.46",
            "y1": "26.37",
            "x2": "61.6",
            "y2": "56.47",
        })
        self.assertEqual(result["accent_base_gradient"]["colors"], ["#ffb669", "#ff6b00"])
        self.assertEqual(result["accent_highlight_gradient"]["color"], "#ffb669")
        self.assertAlmostEqual(result["accent_highlight_gradient"]["start_opacity"], 0.6154277671321837)
        self.assertEqual(result["gray_gradient"]["colors"], ["#d9dcde", "#ffffff"])
        self.assertEqual(len(root.xpath(".//s:linearGradient", namespaces=scan.NS)), 3)
        self.assertEqual(len(root.xpath(".//s:mask", namespaces=scan.NS)), 0)
        self.assertEqual(len(root.xpath(".//s:filter", namespaces=scan.NS)), 0)
        self.assertEqual(len(root.xpath(".//s:clipPath", namespaces=scan.NS)), 0)
        self.assertEqual(len(root.xpath(".//s:image", namespaces=scan.NS)), 0)
        gray = root.xpath(".//*[@data-svg-research='reconstructed-gray-disc']", namespaces=scan.NS)
        accent = root.xpath(".//*[@data-svg-research='reconstructed-accent-disc']", namespaces=scan.NS)
        self.assertEqual(len(gray), 1)
        self.assertEqual(len(accent), 1)
        foreground = root.xpath(".//s:path[@class='foreground']", namespaces=scan.NS)
        self.assertEqual(len(foreground), 1)
        style_text = "".join(root.xpath(".//s:style/text()", namespaces=scan.NS))
        self.assertIn(".foreground", style_text)
        self.assertNotIn(".unused", style_text)

    def test_rejects_scaffold_with_nonconcentric_ring(self) -> None:
        root = etree.fromstring(self._source())
        ring = root.xpath(".//s:g[contains(@style,'mask:url')]/s:circle", namespaces=scan.NS)[0]
        ring.set("cx", "45")
        with self.assertRaises(gradient_mask_reconstruct.ReconstructionError):
            gradient_mask_reconstruct.reconstruct_tree(etree.ElementTree(root))


    def test_gradient_mask_scaffold_accepts_raw_polygon_stripes(self) -> None:
        ns = "http://www.w3.org/2000/svg"
        root = etree.Element(f"{{{ns}}}svg", nsmap={None: ns})
        defs = etree.SubElement(root, f"{{{ns}}}defs")
        for clip_id, radius in (("outer", "32.02"), ("inner", "24.69")):
            clip = etree.SubElement(defs, f"{{{ns}}}clipPath", id=clip_id)
            etree.SubElement(clip, f"{{{ns}}}circle", cx="41.1", cy="41.1", r=radius)
        layer = etree.SubElement(root, f"{{{ns}}}g")
        etree.SubElement(layer, f"{{{ns}}}circle", cx="41.1", cy="41.1", r="41.1")
        outer = etree.SubElement(layer, f"{{{ns}}}g", style="clip-path:url(#outer)")
        for _ in range(20):
            etree.SubElement(outer, f"{{{ns}}}polygon", points="0,0 1,0 1,1")
        masked = etree.SubElement(layer, f"{{{ns}}}g", style="mask:url(#mask)")
        etree.SubElement(masked, f"{{{ns}}}circle", cx="41.1", cy="41.1", r="32.02")
        multiply = etree.SubElement(layer, f"{{{ns}}}g", style="mix-blend-mode:multiply")
        for _ in range(20):
            etree.SubElement(multiply, f"{{{ns}}}circle", cx="41.1", cy="41.1", r="24.69")
        etree.SubElement(layer, f"{{{ns}}}circle", cx="41.1", cy="41.1", r="24.69")
        inner = etree.SubElement(layer, f"{{{ns}}}g", style="clip-path:url(#inner)")
        for _ in range(20):
            etree.SubElement(inner, f"{{{ns}}}polygon", points="0,0 1,0 1,1")

        scaffold = gradient_mask_reconstruct.find_gradient_mask_scaffold(root)
        self.assertEqual(scaffold["inner_geometry"], (41.1, 41.1, 24.69))
        self.assertEqual(scaffold["ring_geometry"], (41.1, 41.1, 32.02))

    def test_gradient_mask_scaffold_matches_relationships_with_hidden_nested_stripes(self) -> None:
        ns = "http://www.w3.org/2000/svg"
        root = etree.Element(f"{{{ns}}}svg", nsmap={None: ns})
        defs = etree.SubElement(root, f"{{{ns}}}defs")
        gradient = etree.SubElement(defs, f"{{{ns}}}linearGradient", id="orange-base")
        etree.SubElement(gradient, f"{{{ns}}}stop", offset="0", **{"stop-color": "#ffb669"})
        etree.SubElement(gradient, f"{{{ns}}}stop", offset="1", **{"stop-color": "#ff6b00"})
        for clip_id, radius in (("outer", "32.02"), ("inner", "24.69")):
            clip = etree.SubElement(defs, f"{{{ns}}}clipPath", id=clip_id)
            etree.SubElement(clip, f"{{{ns}}}circle", cx="41.1", cy="41.1", r=radius)
        mask = etree.SubElement(defs, f"{{{ns}}}mask", id="ring-mask")
        etree.SubElement(mask, f"{{{ns}}}image", href="data:image/png;base64,AAAA")

        layer = etree.SubElement(root, f"{{{ns}}}g", id="layer")
        etree.SubElement(layer, f"{{{ns}}}path", d="M0 0h82v82z")
        outer_wrapper = etree.SubElement(layer, f"{{{ns}}}g", id="outer-wrapper")
        outer = etree.SubElement(outer_wrapper, f"{{{ns}}}g", style="clip-path:url(#outer)")
        for index in range(43):
            etree.SubElement(outer, f"{{{ns}}}rect", x="0", y=str(index), width="82", height="1")
        masked_wrapper = etree.SubElement(layer, f"{{{ns}}}g")
        masked = etree.SubElement(masked_wrapper, f"{{{ns}}}g", style="mask:url(#ring-mask)")
        etree.SubElement(masked, f"{{{ns}}}circle", cx="41.1", cy="41.1", r="32.02")
        multiply = etree.SubElement(layer, f"{{{ns}}}g", style="mix-blend-mode:multiply")
        for index in range(44):
            etree.SubElement(multiply, f"{{{ns}}}circle", cx="41.2", cy="41.1", r="24.69", fill="url(#orange-base)")
        etree.SubElement(layer, f"{{{ns}}}circle", cx="41.1", cy="41.1", r="24.69", fill="url(#orange-base)")
        extra = etree.SubElement(layer, f"{{{ns}}}g", id="extra-non-scaffold")
        etree.SubElement(extra, f"{{{ns}}}path", d="M1 1h1v1z")
        g132 = etree.SubElement(layer, f"{{{ns}}}g", id="g132", style="display:none;clip-path:url(#inner)")
        for index in range(38):
            etree.SubElement(g132, f"{{{ns}}}polygon", points=f"{index},0 {index+1},0 {index+2},2")
        etree.SubElement(layer, f"{{{ns}}}path", d="M10 10h5v5z", attrib={"class": "foreground"})

        scaffold = gradient_mask_reconstruct.find_gradient_mask_scaffold(root)
        self.assertEqual(scaffold["match_mode"], "relationship")
        self.assertEqual(scan.local_name(scaffold["outer_stripes"]), "g")
        self.assertEqual(scaffold["inner_stripes"].get("id"), "g132")
        tree = etree.ElementTree(root)
        result = gradient_mask_reconstruct.reconstruct_tree(tree)
        self.assertEqual(result["outer_stripe_geometry_removed"], 43)
        self.assertEqual(result["inner_stripe_geometry_removed"], 38)
        self.assertEqual(len(root.xpath(".//*[@id='extra-non-scaffold']", namespaces={"s": ns})), 1)
        self.assertEqual(len(root.xpath(".//s:path[@class='foreground']", namespaces={"s": ns})), 1)

    def test_gradient_mask_scaffold_resolves_css_class_structural_properties(self) -> None:
        ns = "http://www.w3.org/2000/svg"
        root = etree.fromstring(self._source())
        style = root.xpath(".//s:style", namespaces=scan.NS)[0]
        style.text = (style.text or "") + (
            ".outerclip{clip-path:url(#outer-clip)}"
            ".ringmask{mask:url(#ring-mask)}"
            ".multiply{mix-blend-mode:multiply}"
            ".innerclip{clip-path:url(#inner-clip)}"
        )
        outer = root.xpath(".//s:g[contains(@style,'clip-path:url(#outer-clip)')]", namespaces=scan.NS)[0]
        masked = root.xpath(".//s:g[contains(@style,'mask:url(#ring-mask)')]", namespaces=scan.NS)[0]
        multiply = root.xpath(".//s:g[contains(@style,'mix-blend-mode:multiply')]", namespaces=scan.NS)[0]
        inner = root.xpath(".//s:g[contains(@style,'clip-path:url(#inner-clip)')]", namespaces=scan.NS)[0]
        for element, class_name in (
            (outer, "outerclip"),
            (masked, "ringmask"),
            (multiply, "multiply"),
            (inner, "innerclip"),
        ):
            element.attrib.pop("style", None)
            element.set("class", class_name)
        diagnostics = gradient_mask_reconstruct.scaffold_diagnostics(root)
        self.assertEqual(len(diagnostics["multiply_groups"]), 1)
        self.assertEqual(len(diagnostics["masked_groups"]), 1)
        self.assertEqual(len(diagnostics["clipped_groups"]), 2)
        scaffold = gradient_mask_reconstruct.find_gradient_mask_scaffold(root)
        self.assertEqual(scaffold["inner_geometry"], (41.1, 41.1, 24.69))
        self.assertEqual(scaffold["ring_geometry"], (41.1, 41.1, 32.02))

    def test_gradient_mask_reconstruction_uses_source_accent_palette(self) -> None:
        root = etree.fromstring(self._source())
        stops = root.xpath(".//s:linearGradient[@id='orange-base']/s:stop", namespaces=scan.NS)
        stops[0].set("stop-color", "#7fd4c1")
        stops[1].set("stop-color", "#39a572")
        result = gradient_mask_reconstruct.reconstruct_tree(etree.ElementTree(root))
        self.assertEqual(result["accent_base_gradient"]["colors"], ["#7fd4c1", "#39a572"])
        self.assertEqual(result["accent_highlight_gradient"]["color"], "#7fd4c1")

    def test_decomposed_gradient_mask_model_uses_concentric_authorial_geometry(self) -> None:
        root = etree.fromstring(self._source())
        result = gradient_mask_model.reconstruct_decomposed_tree(etree.ElementTree(root))
        self.assertEqual(result["model"], "decomposed-concentric")
        self.assertEqual(result["gradient_count"], 5)
        self.assertEqual(result["circle_count"], 5)
        self.assertEqual(result["accent_colors"], ["#ffb669", "#ff6b00"])
        self.assertEqual(result["gray_shadow"]["mode"], "shared-weak")
        self.assertEqual(result["geometry_policy"], "concentric-authorial")
        circles = root.xpath(".//s:g[@data-svg-research='reconstructed-accent-field']/s:circle", namespaces=scan.NS)
        self.assertEqual(len(circles), 3)
        for circle in circles:
            self.assertEqual(circle.get("cx"), "41.1")
            self.assertEqual(circle.get("cy"), "41.1")
            self.assertEqual(circle.get("r"), "24.69")
        self.assertFalse(root.xpath(".//*[@data-svg-research='reconstructed-accent-rim']", namespaces=scan.NS))
        self.assertEqual(len(root.xpath(".//s:linearGradient", namespaces=scan.NS)), 2)
        self.assertEqual(len(root.xpath(".//s:radialGradient", namespaces=scan.NS)), 3)
        self.assertEqual(len(root.xpath(".//s:mask", namespaces=scan.NS)), 0)
        self.assertEqual(len(root.xpath(".//s:filter", namespaces=scan.NS)), 0)
        self.assertEqual(len(root.xpath(".//s:clipPath", namespaces=scan.NS)), 0)
        self.assertEqual(len(root.xpath(".//s:image", namespaces=scan.NS)), 0)

    def test_gray_shadow_fit_detects_strong_shifted_radial_crescent(self) -> None:
        size = 256
        yy, xx = np.mgrid[0:size, 0:size]
        x = (xx + 0.5) * 82.2 / size
        y = (yy + 0.5) * 82.2 / size
        baseline = np.full((size, size, 3), 240.0, dtype=np.float64)
        distance = np.hypot(x - 41.75, y - 41.39) / 32.68
        alpha = 0.50 * np.clip((distance - 0.984) / (1.0 - 0.984), 0.0, 1.0)
        disc = np.hypot(x - 41.1, y - 41.1) <= 32.02
        alpha = np.where(disc, alpha, 0.0)
        source = np.clip(baseline * (1.0 - alpha[..., None]), 0, 255).astype(np.uint8)
        baseline_uint8 = baseline.astype(np.uint8)
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            source_path = directory / "source.png"
            baseline_path = directory / "baseline.png"
            Image.fromarray(source, mode="RGB").save(source_path)
            Image.fromarray(baseline_uint8, mode="RGB").save(baseline_path)
            result = gradient_mask_model.fit_gray_shadow_from_renders(
                source_path,
                baseline_path,
                view_box=(0.0, 0.0, 82.2, 82.2),
                gray_geometry=(41.1, 41.1, 32.02),
            )
        self.assertEqual(result["mode"], "fitted-strong")
        self.assertGreater(result["target_alpha_p99"], 0.2)
        self.assertAlmostEqual(result["cx"], 41.75, delta=0.25)
        self.assertAlmostEqual(result["cy"], 41.39, delta=0.25)
        self.assertAlmostEqual(result["max_opacity"], 0.50, delta=0.15)


class GradientMaskBatchTests(unittest.TestCase):
    def test_load_groups_deduplicates_flattened_gradient_mask_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            scan_path = Path(temporary_directory) / "scan.json"
            scan_path.write_text(
                __import__("json").dumps(
                    {
                        "files": [
                            {"path": r"units\b.svg", "sha256": "aaa", "size_bytes": 10, "classification": "flattened-gradient-mask"},
                            {"path": r"units\a.svg", "sha256": "aaa", "size_bytes": 10, "classification": "flattened-gradient-mask"},
                            {"path": "units/c.svg", "sha256": "bbb", "size_bytes": 20, "classification": "flattened-gradient-mask"},
                            {"path": "units/d.svg", "sha256": "ccc", "size_bytes": 30, "classification": None},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            groups = gradient_mask_batch.load_groups(scan_path)
        self.assertEqual(len(groups), 2)
        first = next(group for group in groups if group["sha256"] == "aaa")
        self.assertEqual(first["count"], 2)
        self.assertEqual(first["paths"], ["units\\a.svg", "units\\b.svg"])

    def test_source_path_accepts_windows_scan_separators(self) -> None:
        root = Path("root")
        self.assertEqual(
            gradient_mask_batch._source_path(root, "units\\scarface-and-cordelia-2-1.svg"),
            root / "units" / "scarface-and-cordelia-2-1.svg",
        )

    def test_run_reconstruction_module_forces_no_render(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            source = directory / "source.svg"
            source.write_text("<svg/>", encoding="utf-8")
            output_dir = directory / "case"

            def fake_run(command, **_kwargs):
                self.assertIn("--no-render", command)
                output_index = command.index("--output-dir") + 1
                manifest_dir = Path(command[output_index])
                manifest_dir.mkdir(parents=True, exist_ok=True)
                (manifest_dir / "manifest.json").write_text(
                    '{"candidate":"candidate.svg"}\n',
                    encoding="utf-8",
                )
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with mock.patch.object(gradient_mask_batch.subprocess, "run", side_effect=fake_run):
                manifest, error = gradient_mask_batch._run_reconstruction_module(
                    module="example.module",
                    source=source,
                    output_dir=output_dir,
                    sizes=(64,),
                    scour=False,
                )

        self.assertIsNone(error)
        self.assertEqual(manifest, {"candidate": "candidate.svg"})

if __name__ == "__main__":
    unittest.main()
