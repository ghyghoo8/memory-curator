import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "plugins" / "memory-curator"
SKILL_ROOT = PLUGIN_ROOT / "skills" / "memory-curator"


class PluginLayoutTest(unittest.TestCase):
    def test_marketplace_points_to_the_bundled_plugin(self) -> None:
        marketplace_path = ROOT / ".agents" / "plugins" / "marketplace.json"
        marketplace = json.loads(marketplace_path.read_text(encoding="utf-8"))

        self.assertEqual(marketplace["name"], "memory-curator")
        self.assertEqual(marketplace["interface"]["displayName"], "Memory Curator")
        self.assertEqual(len(marketplace["plugins"]), 1)

        entry = marketplace["plugins"][0]
        self.assertEqual(entry["name"], "memory-curator")
        self.assertEqual(
            entry["source"],
            {"source": "local", "path": "./plugins/memory-curator"},
        )
        self.assertEqual(
            entry["policy"],
            {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
        )
        self.assertEqual(entry["category"], "Productivity")
        self.assertTrue(PLUGIN_ROOT.is_dir())

    def test_manifest_exposes_the_memory_curator_skill(self) -> None:
        manifest_path = PLUGIN_ROOT / ".codex-plugin" / "plugin.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(manifest["name"], PLUGIN_ROOT.name)
        self.assertEqual(manifest["skills"], "./skills/")
        self.assertRegex(manifest["version"], r"^\d+\.\d+\.\d+")
        self.assertEqual(manifest["interface"]["displayName"], "Memory Curator")
        self.assertTrue((SKILL_ROOT / "SKILL.md").is_file())

        skill_frontmatter = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("\nname: memory-curator\n", skill_frontmatter)

    def test_legacy_installer_links_the_canonical_plugin_skill(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            project.mkdir()

            subprocess.run(
                ["bash", str(ROOT / "install.sh"), "--project"],
                cwd=project,
                check=True,
                capture_output=True,
                text=True,
            )

            installed = project / ".codex" / "skills" / "memory-curator"
            self.assertTrue(installed.is_symlink())
            self.assertEqual(installed.resolve(), SKILL_ROOT.resolve())


class LegacyHookInstallerTests(unittest.TestCase):
    def run_installer(self, project: Path, *, fail_command: str | None = None) -> subprocess.CompletedProcess[str]:
        self.assertIsNotNone(shutil.which("jq"), "installer regression checks require jq")
        temporary = project / "temporary"
        temporary.mkdir(exist_ok=True)
        environment = {**os.environ, "TMPDIR": str(temporary)}
        if fail_command:
            commands = project / "commands"
            commands.mkdir()
            failure = commands / fail_command
            failure.write_text("#!/bin/sh\necho 'injected command failure' >&2\nexit 45\n", encoding="utf-8")
            failure.chmod(0o755)
            environment["PATH"] = str(commands) + os.pathsep + environment["PATH"]
        return subprocess.run(
            ["bash", str(ROOT / "install.sh"), "--project", "--with-claude-hooks"],
            cwd=project, input="y\n", capture_output=True, text=True, env=environment, timeout=15,
        )

    def assert_failed_without_settings_change(self, project: Path, before: bytes | None,
                                             result: subprocess.CompletedProcess[str]) -> None:
        settings = project / ".claude" / "settings.json"
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertNotIn("已注册 hooks", result.stdout)
        if before is None:
            self.assertFalse(settings.exists())
        else:
            self.assertEqual(settings.read_bytes(), before)
        self.assertEqual(list((project / "temporary").iterdir()), [])
        self.assertEqual([path.name for path in settings.parent.iterdir()], [] if before is None else ["settings.json"])

    def test_invalid_json_and_hook_structures_fail_without_overwrite_or_temp_leaks(self) -> None:
        payloads = [
            b"{invalid\n", b"", b"{}\n{}\n", b"[]", b"null",
            b'{"hooks": []}', b'{"hooks": null}', b'{"hooks": {"Stop": "bad"}}',
            b'{"hooks": {"Stop": [{"hooks": {}}]}}',
            b'{"hooks": {"Stop": [{"hooks": ["bad"]}]}}',
        ]
        for payload in payloads:
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as temp_dir:
                project = Path(temp_dir)
                settings = project / ".claude" / "settings.json"
                settings.parent.mkdir()
                settings.write_bytes(payload)

                result = self.run_installer(project)

                self.assert_failed_without_settings_change(project, payload, result)

    def test_jq_failure_is_nonzero_and_preserves_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            settings = project / ".claude" / "settings.json"
            settings.parent.mkdir()
            before = b'{ "env": { "KEEP": "yes" } }\n'
            settings.write_bytes(before)

            result = self.run_installer(project, fail_command="jq")

            self.assert_failed_without_settings_change(project, before, result)

    def test_publish_failure_preserves_existing_or_absent_settings(self) -> None:
        for before in (b'{ "env": { "KEEP": "yes" } }\n', None):
            with self.subTest(existing=before is not None), tempfile.TemporaryDirectory() as temp_dir:
                project = Path(temp_dir)
                settings = project / ".claude" / "settings.json"
                settings.parent.mkdir()
                if before is not None:
                    settings.write_bytes(before)

                result = self.run_installer(project, fail_command="mv")

                self.assert_failed_without_settings_change(project, before, result)

    def test_successful_repeat_keeps_other_hooks_and_does_not_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            settings = project / ".claude" / "settings.json"
            settings.parent.mkdir()
            stop_command = str(SKILL_ROOT / "hooks" / "on-stop.sh")
            push_command = str(SKILL_ROOT / "hooks" / "on-pre-push.sh")
            existing = {
                "env": {"KEEP": "yes"},
                "hooks": {
                    "Stop": [{"matcher": "custom", "custom_option": True,
                              "hooks": [{"type": "command", "command": stop_command},
                                        {"type": "command", "command": "keep-other-hook"}]},
                             {"matcher": "empty-but-preserved", "hooks": []}],
                    "SessionStart": [{"hooks": [{"type": "command", "command": "keep-start"}]}],
                },
            }
            settings.write_text(json.dumps(existing), encoding="utf-8")

            first = self.run_installer(project)
            self.assertEqual(first.returncode, 0, first.stderr)
            after_first = settings.read_bytes()
            second = self.run_installer(project)

            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(after_first, settings.read_bytes())
            merged = json.loads(after_first)
            self.assertEqual(merged["env"], existing["env"])
            self.assertEqual(merged["hooks"]["SessionStart"], existing["hooks"]["SessionStart"])
            self.assertEqual(merged["hooks"]["Stop"], existing["hooks"]["Stop"])
            for event, command in (("Stop", stop_command), ("PreToolUse", push_command)):
                commands = [hook.get("command") for group in merged["hooks"][event] for hook in group["hooks"]]
                self.assertEqual(commands.count(command), 1)
            self.assertEqual(list((project / "temporary").iterdir()), [])
            self.assertEqual([path.name for path in settings.parent.iterdir()], ["settings.json"])

    def test_unique_existing_command_preserves_hook_and_group_options(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            settings = project / ".claude" / "settings.json"
            settings.parent.mkdir()
            existing = {"hooks": {
                event: [{"matcher": matcher, "custom_option": {"keep": True}, "timeout": 15,
                         "hooks": [{"type": "command", "command": str(SKILL_ROOT / "hooks" / script),
                                    "timeout": 90, "custom_option": "preserve-this-hook"}]}]
                for event, matcher, script in (("Stop", "custom-stop", "on-stop.sh"),
                                                ("PreToolUse", "Bash|Read", "on-pre-push.sh"))
            }}
            settings.write_text(json.dumps(existing), encoding="utf-8")

            first = self.run_installer(project)
            self.assertEqual(first.returncode, 0, first.stderr)
            after_first = settings.read_bytes()
            second = self.run_installer(project)

            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(json.loads(after_first), existing)
            self.assertEqual(settings.read_bytes(), after_first)

    def test_ambiguous_duplicate_commands_fail_without_changing_settings(self) -> None:
        for event, script in (("Stop", "on-stop.sh"), ("PreToolUse", "on-pre-push.sh")):
            for same_group in (True, False):
                with self.subTest(event=event, same_group=same_group), tempfile.TemporaryDirectory() as temp_dir:
                    project = Path(temp_dir)
                    settings = project / ".claude" / "settings.json"
                    settings.parent.mkdir()
                    command = str(SKILL_ROOT / "hooks" / script)
                    hooks = [{"type": "command", "command": command, "timeout": timeout} for timeout in (10, 90)]
                    groups = ([{"matcher": "Bash", "hooks": hooks}] if same_group else
                              [{"matcher": matcher, "hooks": [hook]} for matcher, hook in zip(("Bash", "Read"), hooks)])
                    before = json.dumps({"hooks": {event: groups}, "env": {"KEEP": "yes"}}).encode("utf-8")
                    settings.write_bytes(before)

                    result = self.run_installer(project)

                    self.assert_failed_without_settings_change(project, before, result)
                    self.assertIn("ambiguous", result.stderr)

    def test_absent_settings_is_created_only_on_success(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            result = self.run_installer(project)

            self.assertEqual(result.returncode, 0, result.stderr)
            settings = json.loads((project / ".claude" / "settings.json").read_text(encoding="utf-8"))
            self.assertEqual(set(settings["hooks"]), {"Stop", "PreToolUse"})


if __name__ == "__main__":
    unittest.main()
