from __future__ import annotations

import unittest

from lxml import etree

from infinity_svg_research import blend_use_reconstruct
from infinity_svg_research import scan


class CompactBlendUseTests(unittest.TestCase):

    def _reverse_source_with_occluder(
        self, *, face_opacity: str | None = None
    ) -> tuple[etree._Element, etree._Element]:
        svg = etree.Element(f"{{{scan.SVG}}}svg", nsmap={None: scan.SVG, "xlink": scan.XLINK})
        defs = etree.SubElement(svg, f"{{{scan.SVG}}}defs")
        style = etree.SubElement(svg, f"{{{scan.SVG}}}style")
        stack = etree.SubElement(svg, f"{{{scan.SVG}}}g")
        rules = []
        for step_index in range(20):
            translation = 19 - step_index
            step = etree.SubElement(stack, f"{{{scan.SVG}}}g")
            for glyph_index in range(2):
                gradient_id = f"occluded-g-{step_index}-{glyph_index}"
                gradient = etree.SubElement(
                    defs,
                    f"{{{scan.SVG}}}linearGradient",
                    id=gradient_id,
                    gradientTransform=f"translate({translation} 0)",
                )
                etree.SubElement(gradient, f"{{{scan.SVG}}}stop", offset="0")
                etree.SubElement(gradient, f"{{{scan.SVG}}}stop", offset="1")
                class_name = f"occluded-s-{step_index}-{glyph_index}"
                rules.append(f".{class_name}{{fill:url(#{gradient_id})}}")
                x = translation + glyph_index * 3
                etree.SubElement(
                    step,
                    f"{{{scan.SVG}}}path",
                    attrib={"class": class_name, "d": f"M{x},0 l1,0 l0,1 z"},
                )

        face_gradient = etree.SubElement(defs, f"{{{scan.SVG}}}linearGradient", id="face-g")
        etree.SubElement(
            face_gradient,
            f"{{{scan.SVG}}}stop",
            offset="0",
            **{"stop-color": "#00e6ff"},
        )
        etree.SubElement(
            face_gradient,
            f"{{{scan.SVG}}}stop",
            offset="1",
            **{"stop-color": "#ffffff"},
        )
        rules.append(".face{fill:url(#face-g)}")
        face_attrib = {} if face_opacity is None else {"opacity": face_opacity}
        face = etree.SubElement(svg, f"{{{scan.SVG}}}g", attrib=face_attrib)
        for glyph_index in range(2):
            etree.SubElement(
                face,
                f"{{{scan.SVG}}}path",
                attrib={"class": "face", "d": f"M{glyph_index * 3},0 l1,0 l0,1 z"},
            )
        style.text = "".join(rules)
        return svg, stack

    def test_generated_uses_use_svg2_href_and_xy_translation(self) -> None:
        svg = etree.Element(f"{{{scan.SVG}}}svg", nsmap={None: scan.SVG, "xlink": scan.XLINK})
        defs = etree.SubElement(svg, f"{{{scan.SVG}}}defs")
        style = etree.SubElement(svg, f"{{{scan.SVG}}}style")
        stack = etree.SubElement(svg, f"{{{scan.SVG}}}g")
        rules = []
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
                etree.SubElement(gradient, f"{{{scan.SVG}}}stop", offset="0")
                etree.SubElement(gradient, f"{{{scan.SVG}}}stop", offset="1")
                class_name = f"s-{step_index}-{glyph_index}"
                rules.append(f".{class_name}{{fill:url(#{gradient_id})}}")
                x = step_index + glyph_index * 3
                etree.SubElement(
                    step,
                    f"{{{scan.SVG}}}path",
                    attrib={"class": class_name, "d": f"M{x},0 l1,0 l0,1 z"},
                )
        style.text = "".join(rules)

        result = blend_use_reconstruct.rewrite_blend_stacks(etree.ElementTree(svg))
        uses = svg.xpath(".//s:use", namespaces=scan.NS)

        self.assertEqual(result["generated_uses"], 19)
        self.assertEqual(len(uses), 19)
        self.assertEqual(uses[0].get("href"), f"#{result['stacks'][0]['base_id']}")
        self.assertIsNone(uses[0].get(f"{{{scan.XLINK}}}href"))
        self.assertIsNone(uses[0].get("transform"))
        self.assertEqual(uses[0].get("x"), "1")
        self.assertIsNone(uses[0].get("y"))

    def test_zero_translation_front_step_becomes_canonical_base(self) -> None:
        svg = etree.Element(f"{{{scan.SVG}}}svg", nsmap={None: scan.SVG, "xlink": scan.XLINK})
        defs = etree.SubElement(svg, f"{{{scan.SVG}}}defs")
        style = etree.SubElement(svg, f"{{{scan.SVG}}}style")
        stack = etree.SubElement(svg, f"{{{scan.SVG}}}g")
        rules = []
        for step_index in range(20):
            translation = 19 - step_index
            step = etree.SubElement(stack, f"{{{scan.SVG}}}g")
            for glyph_index in range(2):
                gradient_id = f"reverse-g-{step_index}-{glyph_index}"
                gradient = etree.SubElement(
                    defs,
                    f"{{{scan.SVG}}}linearGradient",
                    id=gradient_id,
                    x1="0",
                    y1="0",
                    x2="10",
                    y2="0",
                    gradientUnits="userSpaceOnUse",
                    gradientTransform=f"translate({translation} 0)",
                )
                etree.SubElement(gradient, f"{{{scan.SVG}}}stop", offset="0")
                etree.SubElement(gradient, f"{{{scan.SVG}}}stop", offset="1")
                class_name = f"reverse-s-{step_index}-{glyph_index}"
                rules.append(f".{class_name}{{fill:url(#{gradient_id})}}")
                x = translation + glyph_index * 3
                etree.SubElement(
                    step,
                    f"{{{scan.SVG}}}path",
                    attrib={"class": class_name, "d": f"M{x},0 l1,0 l0,1 z"},
                )
        style.text = "".join(rules)

        result = blend_use_reconstruct.rewrite_blend_stacks(etree.ElementTree(svg))
        stats = result["stacks"][0]
        uses = list(stack)[:-1]
        base = list(stack)[-1]

        self.assertEqual(stats["base_step_index"], 19)
        self.assertEqual(stats["base_paint_translation"], [0.0, 0.0])
        self.assertEqual(base.get("id"), stats["base_id"])
        self.assertTrue(all(etree.QName(use).localname == "use" for use in uses))
        self.assertEqual(uses[0].get("x"), "19")
        self.assertEqual(uses[0].get("href"), f"#{stats['base_id']}")



    def test_exact_opaque_later_face_suppresses_hidden_canonical_endpoint(self) -> None:
        svg, stack = self._reverse_source_with_occluder()

        result = blend_use_reconstruct.rewrite_blend_stacks(etree.ElementTree(svg))
        stats = result["stacks"][0]
        base = svg.xpath(f".//*[@id='{stats['base_id']}']")[0]

        self.assertEqual(result["suppressed_occluded_bases"], 1)
        self.assertTrue(stats["suppressed_occluded_base"])
        self.assertEqual(etree.QName(base.getparent()).localname, "defs")
        self.assertIs(base.getparent().getparent(), stack)
        self.assertEqual(len(stack.xpath("./s:defs", namespaces=scan.NS)), 1)
        self.assertEqual(len(stack.xpath("./s:use", namespaces=scan.NS)), 19)

    def test_translucent_later_face_does_not_suppress_canonical_endpoint(self) -> None:
        svg, stack = self._reverse_source_with_occluder(face_opacity="0.5")

        result = blend_use_reconstruct.rewrite_blend_stacks(etree.ElementTree(svg))
        stats = result["stacks"][0]
        base = svg.xpath(f".//*[@id='{stats['base_id']}']")[0]

        self.assertEqual(result["suppressed_occluded_bases"], 0)
        self.assertFalse(stats["suppressed_occluded_base"])
        self.assertIs(base.getparent(), stack)
        self.assertEqual(len(stack.xpath("./s:defs", namespaces=scan.NS)), 0)



if __name__ == "__main__":
    unittest.main()
