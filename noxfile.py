#!/usr/bin/env -S uv run --script

# /// script
# dependencies = ["nox>=2025.2.9"]
# ///

"""Nox runner."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess  # nosec B404 - only used for the DEVNULL sentinel, never spawns a process directly
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


def _resolve_repo(session: nox.Session) -> str:
    """
    Resolve the current repo's "owner/name" via the GitHub CLI.
    """
    return session.run(
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


def _fetch_release_notes(session: nox.Session, repo: str, version: str) -> str:
    """
    Fetch the generated release notes for the given version using the GitHub CLI.
    """
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


def _reconcile_remote_branch(session: nox.Session, repo: str, branch: str) -> None:
    """
    Handle a `release-{version}` branch that already exists on origin from a prior run.

    An open PR against it is a hard stop (re-running shouldn't silently clobber active
    review); otherwise it's a stale/abandoned branch from a closed PR, so it's safe to
    delete and recreate.
    """
    exists = session.run(
        "git",
        "ls-remote",
        "--exit-code",
        "--heads",
        "origin",
        branch,
        external=True,
        silent=True,
        success_codes=[0, 2],
    ).strip()
    if not exists:
        return

    open_prs = json.loads(
        session.run(
            "gh",
            "pr",
            "list",
            "--repo",
            repo,
            "--head",
            branch,
            "--state",
            "open",
            "--json",
            "url",
            external=True,
            silent=True,
        ),
    )
    if open_prs:
        session.error(
            f"Branch {branch} already has an open PR: {open_prs[0]['url']}\n"
            "Close or merge it, or bump to a different version, before re-running.",
        )

    session.log(f"Branch {branch} already exists on origin with no open PR; deleting the stale branch.")
    session.run(
        "gh",
        "api",
        "-X",
        "DELETE",
        f"repos/{repo}/git/refs/heads/{branch}",
        external=True,
        silent=True,
    )


def _create_release_branch(session: nox.Session, version: str, commit_message: str) -> None:
    """Use gitbutler if available to create a release branch, otherwise fall back to git."""
    branch = f"release-{version}"
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as message_file:
        message_file.write(commit_message)
        message_path = message_file.name

    if shutil.which("but"):
        session.run("but", "commit", branch, "-c", "-F", message_path, external=True)
        session.log(
            f"Created branch {branch} with GitButler.\n"
            f"Review the diff, then run: but pr new {branch} -F {message_path}\n"
            f"Once CI passes and the PR is merged, run: nox -s release_draft -- {version}",
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
            f"Once CI passes and the PR is merged, run: nox -s release_draft -- {version}",
        )


@nox.session(venv_backend="none", default=False)
def release_prep(session: nox.Session) -> None:
    """
    Bump the version, update Changelog.md, and create a release branch + commit.

    Usage: nox -s release_prep -- patch|minor|major|X.Y.Z [--yes]
    """
    parser = argparse.ArgumentParser(prog="nox -s release_prep --")
    parser.add_argument("version", help="Bump keyword (patch/minor/major) or explicit X.Y.Z version")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip the confirmation prompt")
    args = parser.parse_args(session.posargs)

    _release_preflight(session)

    pyproject_text = PYPROJECT_PATH.read_text(encoding="utf-8")
    version = resolve_version(current_version(pyproject_text), args.version)
    repo = _resolve_repo(session)

    _reconcile_remote_branch(session, repo, f"release-{version}")

    notes_body = _fetch_release_notes(session, repo, version)
    today = date.today().isoformat()
    changelog_entry = build_changelog_entry(notes_body, version, today)
    commit_message = build_commit_message(notes_body, version)

    session.log(f"The following entry will be inserted into Changelog.md:\n\n{changelog_entry}")

    if not args.yes:
        answer = input("Write these changes and create the release branch/commit? [y/N] ")
        if answer.strip().lower() not in {"y", "yes"}:
            session.log("Aborted; no files were changed.")
            return

    CHANGELOG_PATH.write_text(
        insert_changelog_entry(CHANGELOG_PATH.read_text(encoding="utf-8"), changelog_entry),
        encoding="utf-8",
    )
    PYPROJECT_PATH.write_text(bump_pyproject_version(pyproject_text, version), encoding="utf-8")

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


def _existing_release(session: nox.Session, tag: str) -> dict | None:
    """
    Look up an already-existing release (draft or published) for `tag`, if any.
    """
    raw = session.run(
        "gh",
        "release",
        "view",
        tag,
        "--json",
        "url,isDraft",
        external=True,
        silent=True,
        success_codes=[0, 1],
        stderr=subprocess.DEVNULL,
    ).strip()
    return json.loads(raw) if raw else None


@nox.session(venv_backend="none", default=False)
def release_draft(session: nox.Session) -> None:
    """
    Draft a release from Changelog.md's notes for an already-merged version.

    Usage: nox -s release_draft -- X.Y.Z
    """
    parser = argparse.ArgumentParser(prog="nox -s release_draft --")
    parser.add_argument("version", help="Already-merged version, e.g. 0.10.3")
    args = parser.parse_args(session.posargs)

    if shutil.which("gh") is None:
        session.error("The `gh` CLI is required but was not found on PATH.")

    tag = f"v{args.version}"

    existing = _existing_release(session, tag)
    if existing is not None:
        state = "an unpublished draft" if existing["isDraft"] else "already published"
        session.error(f"{tag} already has a release ({state}): {existing['url']}")

    session.run("git", "fetch", "origin", "main", external=True, silent=True)
    changelog_text = session.run(
        "git",
        "show",
        "origin/main:Changelog.md",
        external=True,
        silent=True,
    )
    section = extract_changelog_section(changelog_text, args.version)

    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as notes_file:
        notes_file.write(section)
        notes_path = notes_file.name

    release_url = session.run(
        "gh",
        "release",
        "create",
        tag,
        "--title",
        tag,
        "--notes-file",
        notes_path,
        "--target",
        "main",
        "--draft",
        external=True,
        silent=True,
    ).strip()

    session.log(
        f"Created draft release: {release_url}\n"
        'This is NOT live yet. Review it, then click "Publish release" on GitHub — '
        "that click is what triggers the image build/push/Sentry-release/notify flow.",
    )

    # Surface the same prompt in the workflow's job summary; a no-op locally.
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with Path(summary_path).open("a", encoding="utf-8") as summary_file:
            summary_file.write(
                "## Draft release ready\n\n"
                f"[{tag}]({release_url}) has been drafted. "
                "Click **Publish release** on that page to ship it.\n",
            )


if __name__ == "__main__":
    nox.main()
