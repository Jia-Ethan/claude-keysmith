"""Issue 27 agents carrier: owned keysmith.md, no sibling overwrite."""

import json
import sys
from pathlib import Path

import importlib.util

MODULE_PATH = Path(__file__).resolve().parents[1] / "claude-instruct.py"
spec = importlib.util.spec_from_file_location("claude_instruct", MODULE_PATH)
claude_instruct = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = claude_instruct
spec.loader.exec_module(claude_instruct)

from test_claude_instruct import run_cli  # noqa: E402


def test_render_agent_file_has_frontmatter_and_markers():
    text = claude_instruct.render_agent_file(
        "# Title\n\nBody line.\n", "Append line.\n"
    )
    assert text.startswith("---\nname: keysmith\n")
    assert "description:" in text.split("---", 2)[1]
    assert "<!-- claude-keysmith:start name=keysmith-agent -->" in text
    assert "Body line." in text
    assert "Append line." in text
    assert text.strip().endswith("<!-- claude-keysmith:end name=keysmith-agent -->")
    assert claude_instruct.keysmith_owns_agent_file(text)
    assert not claude_instruct.keysmith_owns_agent_file("# user agent\nDo stuff.\n")


def test_install_agents_project_writes_owned_file_and_skips_siblings(tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "repo"
    project.mkdir()
    sibling = project / ".claude" / "agents" / "reviewer.md"
    sibling.parent.mkdir(parents=True)
    sibling.write_text("---\nname: reviewer\n---\nUser agent.\n", encoding="utf-8")

    preview = run_cli(
        [
            "install",
            "--scope",
            "project",
            "--project-dir",
            str(project),
            "--name",
            "rules",
            "--agents",
            "--json",
        ],
        home=home,
        cwd=project,
    )
    payload = json.loads(preview.stdout)
    assert payload["ok"] is True
    assert payload["mode"] == "preview"
    assert payload["target"]["agents_file"].endswith("keysmith.md")
    assert not (project / ".claude" / "agents" / "keysmith.md").exists()
    assert sibling.read_text(encoding="utf-8") == "---\nname: reviewer\n---\nUser agent.\n"

    execute = run_cli(
        [
            "install",
            "--scope",
            "project",
            "--project-dir",
            str(project),
            "--name",
            "rules",
            "--agents",
            "--yes",
            "--json",
        ],
        home=home,
        cwd=project,
    )
    payload = json.loads(execute.stdout)
    assert payload["ok"] is True
    agent_path = project / ".claude" / "agents" / "keysmith.md"
    assert agent_path.is_file()
    body = agent_path.read_text(encoding="utf-8")
    assert claude_instruct.keysmith_owns_agent_file(body)
    assert sibling.read_text(encoding="utf-8") == "---\nname: reviewer\n---\nUser agent.\n"
    assert "@.claude/keysmith/rules.md" in (project / "CLAUDE.md").read_text(encoding="utf-8")


def test_install_agents_dry_run_writes_nothing(tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "repo"
    project.mkdir()
    run_cli(
        [
            "install",
            "--scope",
            "project",
            "--project-dir",
            str(project),
            "--agents",
        ],
        home=home,
        cwd=project,
    )
    assert not (project / ".claude" / "agents").exists()
    assert not (project / "CLAUDE.md").exists()


def test_default_install_does_not_write_agents_file(tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "repo"
    project.mkdir()
    run_cli(
        ["install", "--scope", "project", "--project-dir", str(project), "--yes"],
        home=home,
        cwd=project,
    )
    assert (project / ".claude" / "keysmith" / "claude-project-rules.md").is_file()
    assert not (project / ".claude" / "agents" / "keysmith.md").exists()


def test_install_agents_refuses_foreign_file(tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "repo"
    project.mkdir()
    foreign = project / ".claude" / "agents" / "keysmith.md"
    foreign.parent.mkdir(parents=True)
    original = "---\nname: keysmith\n---\nMine.\n"
    foreign.write_text(original, encoding="utf-8")

    result = run_cli(
        [
            "install",
            "--scope",
            "project",
            "--project-dir",
            str(project),
            "--agents",
            "--yes",
            "--json",
        ],
        home=home,
        cwd=project,
        check=False,
    )
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert "拒绝覆盖" in payload["error"]
    assert foreign.read_text(encoding="utf-8") == original
    assert not (project / "CLAUDE.md").exists()


def test_install_agents_user_scope_path(tmp_path):
    home = tmp_path / "home"
    run_cli(
        ["install", "--scope", "user", "--name", "rules", "--agents", "--yes"],
        home=home,
    )
    agent_path = home / ".claude" / "agents" / "keysmith.md"
    assert agent_path.is_file()
    assert claude_instruct.keysmith_owns_agent_file(agent_path.read_text(encoding="utf-8"))


def test_status_reports_agents_carrier(tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "repo"
    project.mkdir()
    run_cli(
        [
            "install",
            "--scope",
            "project",
            "--project-dir",
            str(project),
            "--name",
            "rules",
            "--agents",
            "--yes",
        ],
        home=home,
        cwd=project,
    )
    payload = json.loads(
        run_cli(
            [
                "status",
                "--scope",
                "project",
                "--project-dir",
                str(project),
                "--name",
                "rules",
                "--json",
            ],
            home=home,
            cwd=project,
        ).stdout
    )
    assert payload["agents_file_exists"] is True
    assert payload["agents_block_exists"] is True
    assert payload["presence"]["agents_file"] is True
    assert payload["alignment"]["agents_block_present"] is True
    assert payload["source_identity"]["agents_sha256"]
    assert payload["installed"] is True


def test_uninstall_agents_removes_owned_file_only(tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "repo"
    project.mkdir()
    sibling = project / ".claude" / "agents" / "reviewer.md"
    sibling.parent.mkdir(parents=True)
    sibling.write_text("keep\n", encoding="utf-8")
    run_cli(
        [
            "install",
            "--scope",
            "project",
            "--project-dir",
            str(project),
            "--name",
            "rules",
            "--agents",
            "--yes",
        ],
        home=home,
        cwd=project,
    )

    without_flag = run_cli(
        [
            "uninstall",
            "--scope",
            "project",
            "--project-dir",
            str(project),
            "--name",
            "rules",
            "--yes",
        ],
        home=home,
        cwd=project,
    )
    assert without_flag.returncode == 0
    assert (project / ".claude" / "agents" / "keysmith.md").is_file()

    execute = run_cli(
        [
            "uninstall",
            "--scope",
            "project",
            "--project-dir",
            str(project),
            "--name",
            "rules",
            "--agents",
            "--yes",
            "--json",
        ],
        home=home,
        cwd=project,
    )
    payload = json.loads(execute.stdout)
    assert payload["ok"] is True
    assert not (project / ".claude" / "agents" / "keysmith.md").exists()
    assert sibling.read_text(encoding="utf-8") == "keep\n"
    backups = list((project / ".claude" / "agents").glob("keysmith.md.bak_*"))
    assert backups


def test_uninstall_agents_leaves_foreign_file(tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "repo"
    project.mkdir()
    foreign = project / ".claude" / "agents" / "keysmith.md"
    foreign.parent.mkdir(parents=True)
    foreign.write_text("---\nname: other\n---\nnope\n", encoding="utf-8")
    run_cli(
        [
            "install",
            "--scope",
            "project",
            "--project-dir",
            str(project),
            "--name",
            "rules",
            "--yes",
        ],
        home=home,
        cwd=project,
    )
    result = run_cli(
        [
            "uninstall",
            "--scope",
            "project",
            "--project-dir",
            str(project),
            "--name",
            "rules",
            "--agents",
            "--yes",
            "--json",
        ],
        home=home,
        cwd=project,
    )
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert foreign.read_text(encoding="utf-8") == "---\nname: other\n---\nnope\n"
    assert any("left intact" in warning for warning in payload["warnings"])


def test_agents_idempotent_rewrite(tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "repo"
    project.mkdir()
    args = [
        "install",
        "--scope",
        "project",
        "--project-dir",
        str(project),
        "--agents",
        "--yes",
    ]
    run_cli(args, home=home, cwd=project)
    first = (project / ".claude" / "agents" / "keysmith.md").read_text(encoding="utf-8")
    run_cli(args, home=home, cwd=project)
    second = (project / ".claude" / "agents" / "keysmith.md").read_text(encoding="utf-8")
    assert first == second
    assert list((project / ".claude" / "agents").glob("keysmith.md.bak_*"))
