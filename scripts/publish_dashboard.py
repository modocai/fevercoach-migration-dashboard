#!/usr/bin/env python3
"""Build a public artifact without writing API responses, git commits, or credentials."""
import argparse
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError

from dashboard_data import ROOT, read_json, require, validate_plan
from public_dashboard import (PublicGitHub, fetch_public, make_state, manifest,
                              validate_manifest, validate_state, write_site)
from sync_github import refresh

REPOSITORY = "modocai/fevercoach-migration-dashboard"


def previous_state(plan, nonce, fetch=fetch_public):
    try:
        state = fetch("state.json", nonce)
    except HTTPError as exc:
        if exc.code != 404:
            raise
        # Bootstrap is allowed only when neither public endpoint exists.
        try:
            fetch("manifest.json", nonce)
        except HTTPError as missing:
            if missing.code == 404:
                return None
            raise
        raise ValueError("incomplete public publication")
    validate_state(state, plan)
    live = fetch("manifest.json", nonce)
    validate_manifest(live)
    require(live == manifest(state), "inconsistent public publication")
    return state


def prepare(plan, previous, client, revision, generation, now):
    if previous is not None:
        validate_state(previous, plan)
        require(generation > previous["generation"], "outdated publication attempt")
    snapshot, failures = refresh(plan, previous["snapshot"] if previous else {}, client, now)
    # A failed first collection must never replace the existing site with blanks.
    require(previous is not None or not failures, "first publication needs all approved sources")
    return make_state(snapshot, plan, revision, generation, now), failures


def guard(revision, generation, nonce, fetch=fetch_public, api=None):
    require(isinstance(revision, str) and re.fullmatch(r"[0-9a-f]{40}", revision), "invalid revision")
    require(type(generation) is int and generation > 0, "invalid generation")
    if api is None:
        def api():
            result = subprocess.run(["gh", "api", f"repos/{REPOSITORY}/commits/main", "--jq", ".sha"],
                                    capture_output=True, text=True, timeout=30)
            require(result.returncode == 0, "cannot verify default branch")
            return result.stdout.strip()
    require(api() == revision, "default branch changed; use the newer run")
    try:
        live = fetch("manifest.json", nonce)
    except HTTPError as exc:
        if exc.code == 404:
            return
        raise
    validate_manifest(live)
    require(generation > live["generation"], "newer publication already exists")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--guard", action="store_true")
    args = parser.parse_args()
    try:
        require(os.environ.get("GITHUB_REPOSITORY") == REPOSITORY, "unexpected repository")
        require(os.environ.get("GITHUB_REF") == "refs/heads/main", "default branch required")
        revision = os.environ["GITHUB_SHA"]
        generation = int(os.environ["GITHUB_RUN_NUMBER"])
        nonce = os.environ["GITHUB_RUN_ID"] + "-" + os.environ["GITHUB_RUN_ATTEMPT"]
        if args.guard:
            guard(revision, generation, nonce)
            print("Publication guard passed.")
            return 0
        require(bool(os.environ.get("GH_TOKEN")), "source-read credential required")
        plan = read_json(ROOT / "data/plan.json")
        validate_plan(plan)
        previous = previous_state(plan, nonce)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        state, failures = prepare(plan, previous, PublicGitHub(), revision, generation, now)
        write_site(ROOT / "_site", state, plan, read_json(ROOT / "data/baselines.json"))
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
            output.write("degraded=" + str(bool(failures)).lower() + "\n")
        print("Validated public artifact prepared" + (" with retained last-good data." if failures else "."))
        return 0
    except Exception:
        # Neither exception text, API output, nor private payloads enter public logs.
        print("Publication stopped: source, cache, configuration, or deployment validation failed. Existing site retained.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
