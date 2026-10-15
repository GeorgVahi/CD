"""Static checks for the skill package shared by Codex and Claude Code (stdlib only)."""
from pathlib import Path
import json
import re
import unittest

SKILL = Path(__file__).resolve().parents[1]
REPOSITORY = SKILL.parents[1]
LINK = re.compile(r"\]\(([^)\s]+)\)")


def frontmatter(text):
    match = re.match(r"---\n(.*?)\n---\n", text, re.S)
    if not match:
        raise AssertionError("SKILL.md has no frontmatter.")
    fields = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip().strip('"')
    return fields


def documents():
    yield from sorted(SKILL.rglob("*.md"))
    for name in ("README.md", "README.ru.md", "CONTRIBUTING.md"):
        if (REPOSITORY / name).is_file():
            yield REPOSITORY / name


class SkillMetadataTests(unittest.TestCase):
    def setUp(self):
        self.fields = frontmatter((SKILL / "SKILL.md").read_text(encoding="utf-8"))

    def test_name_matches_folder_and_spec(self):
        name = self.fields["name"]
        self.assertEqual(name, SKILL.name)
        self.assertRegex(name, r"\A[a-z0-9]+(-[a-z0-9]+)*\Z")
        self.assertLessEqual(len(name), 64)
        # Built-in Claude Code commands that a skill would shadow.
        self.assertNotIn(name, {"cd", "code-review", "review", "loop", "init", "simplify", "run"})

    def test_description_names_both_invocations(self):
        description = self.fields["description"]
        self.assertLessEqual(len(description), 1024)
        self.assertNotRegex(description, r"[<>]")
        self.assertIn("$loop-code-review", description)
        self.assertIn("/loop-code-review", description)

    def test_explicit_only_in_both_hosts(self):
        self.assertEqual(self.fields.get("disable-model-invocation"), "true")
        policy = (SKILL / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertRegex(policy, r"allow_implicit_invocation:\s*false")
        self.assertIn("$loop-code-review", policy)

    def test_host_selection_routes_to_both_branches(self):
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        section = text.split("## Host selection", 1)[1].split("\n## ", 1)[0]
        self.assertIn("references/runtime-recovery.md", section)
        self.assertIn("references/claude-code.md", section)
        self.assertLess(text.index("## Host selection"), text.index("## 0. Select an executor"))

    def test_relative_links_resolve(self):
        for document in documents():
            for target in LINK.findall(document.read_text(encoding="utf-8")):
                if re.match(r"[a-z]+:", target) or target.startswith("#"):
                    continue
                with self.subTest(document=document.name, target=target):
                    self.assertTrue((document.parent / target.split("#", 1)[0]).exists())

    def test_old_invocation_name_is_gone(self):
        for document in documents():
            with self.subTest(document=document.name):
                text = document.read_text(encoding="utf-8")
                self.assertIsNone(re.search(r"\$cd\b(?!-)", text.replace("`$cd`", "")))
                self.assertNotIn("skills/cd/", text)

    def test_report_schema_parses(self):
        schema = json.loads((SKILL / "scripts" / "agent-report.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(set(schema["required"]), {"status", "report", "changed_paths"})

    def test_licenses_are_identical(self):
        if not (REPOSITORY / "LICENSE").is_file():
            self.skipTest("Installed skill folder without the repository root.")
        self.assertEqual((REPOSITORY / "LICENSE").read_bytes(), (SKILL / "LICENSE").read_bytes())


if __name__ == "__main__":
    unittest.main()
