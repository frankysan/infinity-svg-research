from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from infinity_svg_research import vyo_review


class _FakeStdin:
    def __init__(self, process):
        self.process = process
        self.closed = False

    def write(self, text):
        self.process.commands.append(text)
        if text.strip() == "quit":
            self.process.returncode = 0
            return len(text)
        if self.process.fail_render and "export-do" in text:
            self.process.returncode = 1
            return len(text)
        destination = None
        for action in text.split(";"):
            action = action.strip()
            if action.startswith("export-filename:"):
                destination = Path(action.split(":", 1)[1])
        if destination is not None and "export-do" in text:
            destination.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGBA", (96, 48), (255, 255, 255, 255)).save(destination)
        return len(text)

    def flush(self):
        return None

    def close(self):
        self.closed = True


class _FakeProcess:
    def __init__(self, *, fail_render=False):
        self.returncode = None
        self.fail_render = fail_render
        self.commands = []
        self.stdin = _FakeStdin(self)

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if self.returncode is None:
            raise subprocess.TimeoutExpired("fake-inkscape", timeout)
        return self.returncode

    def terminate(self):
        self.returncode = -15

    def kill(self):
        self.returncode = -9


class _FakeProcessFactory:
    def __init__(self, *, fail_first=False):
        self.fail_first = fail_first
        self.processes = []

    def __call__(self, *args, **kwargs):
        process = _FakeProcess(fail_render=self.fail_first and not self.processes)
        self.processes.append(process)
        return process


class DecisionTests(unittest.TestCase):
    def report(self):
        return {
            "summary": {},
            "assets": [
                {
                    "army_path": "units/example-1-1.svg",
                    "scope": "unit",
                    "subjects": ["example"],
                    "unit_slugs": ["example"],
                    "profile_names": ["Standard"],
                    "identity_status": "name-candidate",
                    "action": "reuse",
                    "evidence": [],
                    "source_assets": [
                        {"path": "units/example-1-1.svg", "sha256": "army", "url": "x"}
                    ],
                    "candidates": [
                        {
                            "path": "Faction/Example [Vyo].svg",
                            "sha256": "vyo",
                            "subject": "Example",
                            "tags": ["N3"],
                            "matched_by": ["exact-normalized-name"],
                            "action": "reuse",
                            "reasons": [],
                        }
                    ],
                }
            ],
        }

    def test_reuse_review_records_profile_and_hashes(self):
        updated = vyo_review.update_decisions(
            self.report(),
            {"rules": []},
            {
                "army_path": "units/example-1-1.svg",
                "decision": "reuse",
                "vyo_paths": ["Faction/Example [Vyo].svg"],
                "reasons": [],
                "evidence": "Visual comparison: same device and composition.",
            },
        )
        rule = updated["rules"][0]
        self.assertEqual(rule["status"], "reviewed-match")
        self.assertEqual(rule["action"], "reuse")
        self.assertEqual(
            rule["review_source_assets"],
            [{"path": "units/example-1-1.svg", "sha256": "army"}],
        )
        self.assertEqual(
            rule["review_vyo_assets"],
            [{"path": "Faction/Example [Vyo].svg", "sha256": "vyo"}],
        )

    def test_cleanup_requires_reason_and_evidence(self):
        base = {
            "army_path": "units/example-1-1.svg",
            "decision": "cleanup",
            "vyo_paths": ["Faction/Example [Vyo].svg"],
            "reasons": [],
            "evidence": "review",
        }
        with self.assertRaisesRegex(ValueError, "reason"):
            vyo_review.update_decisions(self.report(), {"rules": []}, base)
        base["reasons"] = ["align-palette-to-first-party"]
        base["evidence"] = ""
        with self.assertRaisesRegex(ValueError, "evidence"):
            vyo_review.update_decisions(self.report(), {"rules": []}, base)

    def test_confirmed_missing_is_guarded(self):
        payload = {
            "army_path": "units/example-1-1.svg",
            "decision": "missing",
            "vyo_paths": [],
            "reasons": [],
            "evidence": "Reviewed the relevant archive drawings.",
            "confirm_missing": False,
        }
        with self.assertRaisesRegex(ValueError, "explicit confirmation"):
            vyo_review.update_decisions(self.report(), {"rules": []}, payload)
        payload["confirm_missing"] = True
        rule = vyo_review.update_decisions(self.report(), {"rules": []}, payload)["rules"][0]
        self.assertEqual(rule["status"], "confirmed-missing")
        self.assertNotIn("vyo_paths", rule)

    def test_unresolved_removes_exact_review_but_not_alias_rules(self):
        decisions = {
            "rules": [
                {
                    "army_subjects": ["example"],
                    "status": "alias-candidate",
                    "evidence": "name lead",
                },
                {
                    "army_paths": ["units/example-1-1.svg"],
                    "status": "reviewed-match",
                    "vyo_paths": ["Faction/Example [Vyo].svg"],
                    "action": "reuse",
                    "evidence": "old review",
                },
            ]
        }
        updated = vyo_review.update_decisions(
            self.report(),
            decisions,
            {"army_path": "units/example-1-1.svg", "decision": "unresolved"},
        )
        self.assertEqual(len(updated["rules"]), 1)
        self.assertEqual(updated["rules"][0]["status"], "alias-candidate")

    def test_subject_scoped_review_is_not_rewritten(self):
        decisions = {
            "rules": [
                {
                    "army_subjects": ["example"],
                    "status": "reviewed-match",
                    "vyo_paths": ["Faction/Example [Vyo].svg"],
                    "evidence": "legacy broad review",
                }
            ]
        }
        with self.assertRaisesRegex(ValueError, "subject-scoped"):
            vyo_review.update_decisions(
                self.report(),
                decisions,
                {"army_path": "units/example-1-1.svg", "decision": "unresolved"},
            )

    def test_public_state_exposes_only_exact_editable_review(self):
        decisions = {
            "rules": [
                {
                    "army_paths": ["units/example-1-1.svg"],
                    "status": "reviewed-match",
                    "action": "reuse",
                    "vyo_paths": ["Faction/Example [Vyo].svg"],
                    "evidence": "review",
                }
            ]
        }
        state = vyo_review.public_state(self.report(), decisions)
        self.assertEqual(state["assets"][0]["review"]["action"], "reuse")
        self.assertEqual(state["assets"][0]["army_source"]["sha256"], "army")


class AssetTests(unittest.TestCase):
    def test_safe_svg_path_rejects_escape_and_non_svg(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "ok.svg").write_text("<svg/>", encoding="utf-8")
            self.assertEqual(vyo_review.safe_svg_path(root, "ok.svg"), (root / "ok.svg").resolve())
            with self.assertRaises(ValueError):
                vyo_review.safe_svg_path(root, "../escape.svg")
            with self.assertRaises(ValueError):
                vyo_review.safe_svg_path(root, "notes.txt")

    def test_square_framing_preserves_transparency_and_centers_art(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.png"
            target = root / "target.png"
            image = Image.new("RGBA", (80, 40), (0, 0, 0, 0))
            for x in range(10, 70):
                for y in range(5, 35):
                    image.putpixel((x, y), (255, 0, 0, 255))
            image.save(source)
            vyo_review._fit_square(source, target, 200)
            with Image.open(target) as framed:
                self.assertEqual(framed.size, (200, 200))
                bbox = framed.getbbox()
                self.assertIsNotNone(bbox)
                self.assertEqual((bbox[0] + bbox[2]) // 2, 100)
                self.assertEqual((bbox[1] + bbox[3]) // 2, 100)

    def test_atomic_json_write_is_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "decision.json"
            vyo_review.atomic_write_json(path, {"rules": [{"evidence": "åäö"}]})
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["rules"][0]["evidence"], "åäö")


class PersistentRendererTests(unittest.TestCase):
    def test_shell_is_reused_for_multiple_exports_and_closed_cleanly(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.svg"
            source.write_text("<svg/>", encoding="utf-8")
            factory = _FakeProcessFactory()
            renderer = vyo_review.PersistentInkscapeShell(
                "inkscape",
                log_path=root / "inkscape.log",
                process_factory=factory,
            )
            renderer.start()
            renderer.render(source, root / "one.png", width=256)
            renderer.render(source, root / "two.png", width=512)
            self.assertEqual(renderer.starts, 1)
            self.assertEqual(len(factory.processes), 1)
            render_commands = [
                command for command in factory.processes[0].commands if "export-do" in command
            ]
            self.assertEqual(len(render_commands), 2)
            self.assertIn("export-area-drawing", render_commands[0])
            self.assertIn("file-close", render_commands[0])
            renderer.close()
            self.assertIn("quit\n", factory.processes[0].commands)

    def test_dead_shell_is_restarted_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.svg"
            source.write_text("<svg/>", encoding="utf-8")
            destination = root / "render.png"
            factory = _FakeProcessFactory(fail_first=True)
            renderer = vyo_review.PersistentInkscapeShell(
                "inkscape",
                log_path=root / "inkscape.log",
                process_factory=factory,
            )
            renderer.start()
            renderer.render(source, destination, width=256)
            self.assertTrue(destination.is_file())
            self.assertEqual(renderer.starts, 2)
            self.assertEqual(renderer.restarts, 1)
            renderer.close()

    def test_review_cache_avoids_second_shell_export(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.svg"
            source.write_text("<svg/>", encoding="utf-8")
            factory = _FakeProcessFactory()
            renderer = vyo_review.PersistentInkscapeShell(
                "inkscape",
                log_path=root / "inkscape.log",
                process_factory=factory,
            )
            renderer.start()
            first = vyo_review.render_review_png(
                source, root / "cache", renderer=renderer, size=128
            )
            second = vyo_review.render_review_png(
                source, root / "cache", renderer=renderer, size=128
            )
            self.assertEqual(first, second)
            commands = [
                command for command in factory.processes[0].commands if "export-do" in command
            ]
            self.assertEqual(len(commands), 1)
            renderer.close()


if __name__ == "__main__":
    unittest.main()
