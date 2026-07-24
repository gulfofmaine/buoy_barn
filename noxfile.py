#!/usr/bin/env -S uv run --script

# /// script
# dependencies = ["nox>=2025.2.9"]
# ///

"""Nox runner."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import tempfile
from datetime import date
from pathlib import Path

import nox

DIR = Path(__file__).parent.resolve() / "app"
PROJECT = nox.project.load_toml(DIR / "pyproject.toml")

nox.needs_version = ">=2025.2.9"
nox.options.default_venv_backend = "uv|virtualenv"

PYPROJECT_PATH = DIR / "pyproject.toml"
CHANGELOG_PATH = DIR.parent / "Changelog.md"

VERSION_LINE_RE = re.compile(r'(?m)^version = "(.*)"$')
EXPLICIT_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
NOTES_COMMENT_RE = re.compile(r"^<!--.*?-->\n*", re.DOTALL)
UPCOMING_HEADING_RE = re.compile(r"(?m)^## Upcoming \(unknown release\)$")
HEADING_RE = re.compile(r"(?m)^## ")


@nox.session
def lint(session: nox.Session) -> None:
    """
    Run the linter.
    """
    session.install("prek")
    session.run(
        "prek",
        "run",
        "--all-files",
        "--show-diff-on-failure",
        *session.posargs,
    )


@nox.session
def tests(session: nox.Session) -> None:
    """
    Run the unit and regular tests.
    """
    session.run(
        "docker",
        "compose",
        "-f",
        "docker-compose.test.yaml",
        "run",
        "--rm",
        "-e",
        "DJANGO_ENV=test",
        "web-test",
        "uv",
        "run",
        "pytest",
        "--cov=.",
        "--cov-config=tox.ini",
        "--cov-report=xml:./coverage.xml",
        external=True,
    )


def current_version(pyproject_text: str) -> str:
    """
    Read the current `version = "..."` value out of app/pyproject.toml's text.
    """
    match = VERSION_LINE_RE.search(pyproject_text)
    if match is None:
        raise ValueError('Could not find a `version = "..."` line in app/pyproject.toml')
    return match.group(1)


def resolve_version(current: str, posarg: str) -> str:
    """
    Resolve a bump keyword (patch/minor/major) or explicit X.Y.Z posarg to a target version.
    """
    if EXPLICIT_VERSION_RE.match(posarg):
        return posarg

    major, minor, patch = (int(part) for part in current.split("."))
    if posarg == "major":
        return f"{major + 1}.0.0"
    if posarg == "minor":
        return f"{major}.{minor + 1}.0"
    if posarg == "patch":
        return f"{major}.{minor}.{patch + 1}"

    raise ValueError(f"Unrecognized version or bump keyword: {posarg!r}")


def bump_pyproject_version(pyproject_text: str, new_version: str) -> str:
    """
    Replace the version line in app/pyproject.toml's text with new_version.
    """
    return VERSION_LINE_RE.sub(f'version = "{new_version}"', pyproject_text, count=1)


def strip_notes_comment(notes_body: str) -> str:
    """
    Strip the leading HTML comment (and following blank line) `gh api generate-notes` adds.
    """
    return NOTES_COMMENT_RE.sub("", notes_body, count=1)


def build_changelog_entry(notes_body: str, version: str, release_date: str) -> str:
    """
    Build the Changelog.md entry variant of the generated release notes.
    """
    stripped = strip_notes_comment(notes_body)
    entry = stripped.replace("## What's Changed", f"## {version} - {release_date}", 1)
    return entry.strip() + "\n"


def build_commit_message(notes_body: str, version: str) -> str:
    """
    Build the commit/PR-message variant of the generated release notes.
    """
    stripped = strip_notes_comment(notes_body)
    body = stripped.replace("## What's Changed\n", "", 1).strip()
    return f"Release - {version}\n\n{body}\n"


def insert_changelog_entry(changelog_text: str, entry: str) -> str:
    """
    Splice a new entry into Changelog.md's text, right after the Upcoming block.
    """
    upcoming_match = UPCOMING_HEADING_RE.search(changelog_text)
    if upcoming_match is None:
        raise ValueError(
            "Could not find the '## Upcoming (unknown release)' heading in Changelog.md",
        )

    next_heading = HEADING_RE.search(changelog_text, upcoming_match.end())
    insert_at = next_heading.start() if next_heading else len(changelog_text)

    return changelog_text[:insert_at] + entry.rstrip("\n") + "\n\n" + changelog_text[insert_at:]


def extract_changelog_section(changelog_text: str, version: str) -> str:
    """
    Pull the already-merged Changelog.md section for `version` back out of its text.
    """
    heading_re = re.compile(rf"(?m)^## {re.escape(version)} - .*$")
    match = heading_re.search(changelog_text)
    if match is None:
        raise ValueError(f"Could not find a Changelog.md section for version {version}")

    next_heading = HEADING_RE.search(changelog_text, match.end())
    end = next_heading.start() if next_heading else len(changelog_text)
    return changelog_text[match.start() : end].strip() + "\n"


def _release_preflight(session: nox.Session) -> None:
    """
    Perform preflight checks before starting a release:
    ensure the working tree is clean and the GitHub CLI is available.
    """
    status = session.run("git", "status", "--porcelain", external=True, silent=True)
    if status.strip():
        session.error("Working tree is dirty; commit or stash changes before releasing.")
    if shutil.which("gh") is None:
        session.error("The `gh` CLI is required but was not found on PATH.")


def _fetch_release_notes(session: nox.Session, version: str) -> str:
    """
    Fetch the generated release notes for the given version using the GitHub CLI.
    """
    repo = session.run(
        "gh",
        "repo",
        "view",
        "--json",
        "nameWithOwner",
        "-q",
        ".nameWithOwner",
        external=True,
        silent=True,
    ).strip()
    raw = session.run(
        "gh",
        "api",
        f"repos/{repo}/releases/generate-notes",
        "-f",
        f"tag_name=v{version}",
        external=True,
        silent=True,
    )
    return json.loads(raw)["body"]


def _create_release_branch(session: nox.Session, version: str, commit_message: str) -> None:
    """Use gitbutler if available to create a release branch, otherwise fall back to git."""
    branch = f"release-{version}"
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as message_file:
        message_file.write(commit_message)
        message_path = message_file.name

    if shutil.which("but"):
        session.run("but", "commit", branch, "-c", "-F", message_path, external=True)
        session.log(
            f"Created branch {branch} with GitButler.\n"
            f"Review the diff, then run: but pr new {branch} -F {message_path}\n"
            f"Once CI passes and the PR is merged, run: nox -s publish_release -- {version}",
        )
    else:
        session.run("git", "switch", "-c", branch, external=True)
        session.run("git", "add", "-u", external=True)
        session.run("git", "commit", "-F", message_path, external=True)
        session.log(
            f"Created branch {branch} with git.\n"
            "Review the diff, then run:\n"
            f"  git push -u origin {branch} && gh pr create --draft "
            '--title "$(git log -1 --pretty=%s)" --body "$(git log -1 --pretty=%b)"\n'
            f"Once CI passes and the PR is merged, run: nox -s publish_release -- {version}",
        )


@nox.session(venv_backend="none", default=False)
def release(session: nox.Session) -> None:
    """
    Bump the version, update Changelog.md, and create a release branch + commit.

    Usage: nox -s release -- patch|minor|major|X.Y.Z [--yes]
    """
    parser = argparse.ArgumentParser(prog="nox -s release --")
    parser.add_argument("version", help="Bump keyword (patch/minor/major) or explicit X.Y.Z version")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip the confirmation prompt")
    args = parser.parse_args(session.posargs)

    _release_preflight(session)

    pyproject_text = PYPROJECT_PATH.read_text()
    version = resolve_version(current_version(pyproject_text), args.version)

    notes_body = _fetch_release_notes(session, version)
    today = date.today().isoformat()
    changelog_entry = build_changelog_entry(notes_body, version, today)
    commit_message = build_commit_message(notes_body, version)

    session.log(f"The following entry will be inserted into Changelog.md:\n\n{changelog_entry}")

    if not args.yes:
        answer = input("Write these changes and create the release branch/commit? [y/N] ")
        if answer.strip().lower() not in {"y", "yes"}:
            session.log("Aborted; no files were changed.")
            return

    CHANGELOG_PATH.write_text(insert_changelog_entry(CHANGELOG_PATH.read_text(), changelog_entry))
    PYPROJECT_PATH.write_text(bump_pyproject_version(pyproject_text, version))

    # A hook exit code of 1 just means uv-lock (or pyproject-fmt) auto-fixed something here.
    session.run(
        "prek",
        "run",
        "--files",
        "app/pyproject.toml",
        "Changelog.md",
        external=True,
        success_codes=[0, 1],
    )

    _create_release_branch(session, version, commit_message)


@nox.session(venv_backend="none", default=False)
def publish_release(session: nox.Session) -> None:
    """
    Publish a merged release: create the GitHub release from Changelog.md's notes.

    Usage: nox -s publish_release -- X.Y.Z
    """
    parser = argparse.ArgumentParser(prog="nox -s publish_release --")
    parser.add_argument("version", help="Already-released version, e.g. 0.10.3")
    args = parser.parse_args(session.posargs)

    if shutil.which("gh") is None:
        session.error("The `gh` CLI is required but was not found on PATH.")

    session.run("git", "fetch", "origin", "main", external=True, silent=True)
    changelog_text = session.run(
        "git",
        "show",
        "origin/main:Changelog.md",
        external=True,
        silent=True,
    )
    section = extract_changelog_section(changelog_text, args.version)

    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as notes_file:
        notes_file.write(section)
        notes_path = notes_file.name

    session.run(
        "gh",
        "release",
        "create",
        f"v{args.version}",
        "--title",
        f"v{args.version}",
        "--notes-file",
        notes_path,
        "--target",
        "main",
        external=True,
    )


if __name__ == "__main__":
    nox.main()
