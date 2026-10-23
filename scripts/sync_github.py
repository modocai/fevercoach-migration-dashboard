#!/usr/bin/env python3
"""Read GitHub evidence using gh authentication; never change Issues or Projects."""
import argparse
import base64
import json
import subprocess
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from dashboard_data import (ROOT, project_issues, project_items, project_wix,
                            read_json, require, validate_plan, validate_snapshot, write_json)


class FetchError(Exception):
    pass


class GitHub:
    def api(self, endpoint, *args):
        result = subprocess.run(["gh", "api", endpoint, *args], capture_output=True, text=True, timeout=120)
        if result.returncode:
            # Do not persist/log API bodies or credentials in a public artifact.
            message = result.stderr.lower()
            code = ("project_read_permission_required" if "read:project" in message else
                    "not_found" if "404" in message else "github_request_failed")
            raise FetchError(code)
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise FetchError("invalid_github_response") from exc

    def issues(self, plan):
        pages = self.api(f"repos/{plan['repository']}/issues?state=all&per_page=100", "--paginate", "--slurp")
        return project_issues([issue for page in pages for issue in page], plan)

    def project(self, plan):
        query = """query($owner:String!,$number:Int!,$cursor:String) {
          organization(login:$owner) { projectV2(number:$number) {
            items(first:100,after:$cursor) { pageInfo {hasNextPage endCursor} nodes {
              content { __typename ... on Issue {number repository {nameWithOwner}} }
              fieldValues(first:100) {pageInfo {hasNextPage} nodes {
                ... on ProjectV2ItemFieldSingleSelectValue {name field {... on ProjectV2SingleSelectField {name}}}
                ... on ProjectV2ItemFieldDateValue {date field {... on ProjectV2Field {name}}}
              }}
            }}
          }}
        }"""
        nodes, cursor, seen = [], None, set()
        while True:
            args = ["-f", f"query={query}", "-f", f"owner={plan['project']['owner']}",
                    "-F", f"number={plan['project']['number']}"]
            if cursor:
                args += ["-f", f"cursor={cursor}"]
            result = self.api("graphql", *args)
            require(not result.get("errors"), "Project query incomplete")
            project = (result.get("data", {}).get("organization") or {}).get("projectV2")
            require(project is not None, "Project not accessible")
            items = project["items"]
            for item in items["nodes"]:
                require(not item["fieldValues"]["pageInfo"]["hasNextPage"], "Project field response truncated")
            nodes.extend(items["nodes"])
            if not items["pageInfo"]["hasNextPage"]:
                break
            cursor = items["pageInfo"]["endCursor"]
            require(cursor and cursor not in seen, "invalid Project pagination")
            seen.add(cursor)
        return project_items(nodes, plan)

    def wix(self, plan):
        repo = plan["repository"]
        sha = self.api(f"repos/{repo}/commits/main")["sha"]
        review_state, pr_url = "main", None
        path = "docs/wix-export-status.json"
        try:
            file = self.api(f"repos/{repo}/contents/{path}?ref={sha}")
        except FetchError as exc:
            if str(exc) != "not_found":
                raise
            pr = self.api(f"repos/{repo}/pulls/29")
            require(pr["state"] == "open" and not pr["merged_at"], "no current Wix status source")
            require(pr["head"]["repo"]["full_name"] == repo, "unexpected Wix PR source")
            sha, review_state, pr_url = pr["head"]["sha"], "open_pr", pr["html_url"]
            file = self.api(f"repos/{repo}/contents/{path}?ref={sha}")
        require(file.get("encoding") == "base64", "unexpected content encoding")
        raw = json.loads(base64.b64decode(file["content"]))
        return {"data": project_wix(raw), "source_sha": sha, "review_state": review_state,
                "source_url": f"https://github.com/{repo}/blob/{sha}/{path}", "pr_url": pr_url}


def refresh(plan, previous, client, now):
    snapshot = deepcopy(previous)
    snapshot["schema_version"] = 1
    failures = []
    for name in ["issues", "project", "wix"]:
        old = snapshot.get(name, {})
        try:
            result = getattr(client, name)(plan)
            new = {"status": "ok", "attempted_at": now, "last_success_at": now, "error": None}
            new.update(result if name == "wix" else {"items": result})
            validate_snapshot({"schema_version": 1, name: new}, plan, sources=(name,))
            snapshot[name] = new
        except (FetchError, ValueError, KeyError, TypeError, OSError, subprocess.TimeoutExpired) as exc:
            # A partial/failed response never destroys the last successful data.
            old.update({"status": "error", "attempted_at": now,
                        "last_success_at": old.get("last_success_at"),
                        "error": str(exc) if isinstance(exc, FetchError) else "invalid_or_unavailable_source"})
            snapshot[name] = old
            failures.append(name)
    return snapshot, failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data/snapshot.json")
    args = parser.parse_args()
    plan = read_json(ROOT / "data/plan.json")
    validate_plan(plan)
    previous = read_json(args.output) if args.output.exists() else {}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    snapshot, failures = refresh(plan, previous, GitHub(), now)
    validate_snapshot(snapshot, plan)
    write_json(args.output, snapshot)
    for name in ["issues", "project", "wix"]:
        source = snapshot[name]
        print(f"{name}: {source['status']}" + (f" ({source['error']})" if source["error"] else ""))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
