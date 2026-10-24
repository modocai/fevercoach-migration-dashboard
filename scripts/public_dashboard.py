"""Strict publication boundary. Private API responses never become build artifacts."""
import hashlib
import json
import re
from pathlib import Path
from urllib.request import HTTPRedirectHandler, Request, build_opener

from dashboard_data import (ROOT, require, timestamp, validate_snapshot, project_wix)
from sync_github import FetchError, GitHub

BASE = "https://modocai.github.io/fevercoach-migration-dashboard/"
MAX_STATE_BYTES = 512 * 1024
ERRORS = {None, "project_read_permission_required", "not_found", "github_request_failed",
          "invalid_github_response", "invalid_or_unavailable_source", "approved_wix_source_unavailable"}
FILES = {"index.html", "migration-dashboard.html", "state.json", "manifest.json", "assets/auto-refresh.js", ".nojekyll"}


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def catalog_id(plan):
    return digest({"repository": plan["repository"], "owner": plan["project"]["owner"],
                   "project": plan["project"]["number"], "issues": sorted(t["number"] for t in plan["tasks"])})


class PublicGitHub(GitHub):
    def issues(self, plan):
        owner, repo = plan["repository"].split("/")
        # Fixed integer IDs; never fetch bodies, titles, comments, or assignee profiles.
        fields = " ".join(f'i{t["number"]}:issue(number:{t["number"]}) {{number state stateReason}}'
                          for t in plan["tasks"])
        query = 'query { repository(owner:' + json.dumps(owner) + ',name:' + json.dumps(repo) + ') {' + fields + '} }'
        result = self.api("graphql", "-f", "query=" + query)
        require(not result.get("errors"), "incomplete issue response")
        source = result["data"]["repository"]
        items = []
        for task in plan["tasks"]:
            item = source[f'i{task["number"]}']
            require(item and item["number"] == task["number"], "missing approved issue")
            state = item["state"].lower()
            require(state in {"open", "closed"}, "unexpected issue state")
            reason = (item.get("stateReason") or "").lower() or None
            items.append({"number": item["number"], "state": state,
                          "state_reason": reason if reason in {None, "completed", "not_planned", "reopened"} else None})
        return items

    def wix(self, plan):
        import base64
        repo = plan["repository"]
        sha = self.api(f"repos/{repo}/commits/main")["sha"]
        path = "docs/wix-export-status.json"
        try:
            file = self.api(f"repos/{repo}/contents/{path}?ref={sha}")
        except FetchError as exc:
            if str(exc) == "not_found":
                raise FetchError("approved_wix_source_unavailable") from exc
            raise
        require(file.get("encoding") == "base64", "unexpected source encoding")
        raw = base64.b64decode(file["content"])
        require(len(raw) <= MAX_STATE_BYTES, "source response too large")
        return {"data": project_wix(json.loads(raw)), "source_sha": sha,
                "source_url": f"https://github.com/{repo}/blob/{sha}/{path}",
                "review_state": "main", "pr_url": None}


def public_snapshot(snapshot, plan):
    """Publish only fixed enums, numbers, validated timestamps, and approved source links."""
    result = {"schema_version": 1}
    for name in ["issues", "project", "wix"]:
        source = snapshot[name]
        error = source.get("error")
        error = error if error in ERRORS else "invalid_or_unavailable_source"
        section = {"status": source["status"], "attempted_at": source["attempted_at"],
                   "last_success_at": source.get("last_success_at"), "error": error}
        if "items" in source:
            if name == "issues":
                section["items"] = [{"number": item["number"], "state": item["state"],
                                      "state_reason": item.get("state_reason") if item.get("state_reason") in
                                      {None, "completed", "not_planned", "reopened"} else None}
                                     for item in source["items"]]
            else:
                section["items"] = [{"number": item["number"], "status": item["status"], "due_date": None}
                                     for item in source["items"]]
        if name == "wix" and "data" in source:
            sha = source["source_sha"]
            require(isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{40}", sha), "invalid source revision")
            require(source["review_state"] == "main" and source.get("pr_url") is None,
                    "unreviewed source cannot be published automatically")
            section.update({"data": project_wix(source["data"]), "source_sha": sha,
                            "source_url": f'https://github.com/{plan["repository"]}/blob/{sha}/docs/wix-export-status.json',
                            "review_state": "main", "pr_url": None})
        result[name] = section
    validate_snapshot(result, plan)
    return result


def validate_public_snapshot(snapshot, plan):
    require(public_snapshot(snapshot, plan) == snapshot, "non-public fields in publication")


def make_state(snapshot, plan, revision, generation, now):
    require(re.fullmatch(r"[0-9a-f]{40}", revision) is not None, "invalid build revision")
    require(type(generation) is int and generation > 0, "invalid generation")
    timestamp(now)
    state = {"schema_version": 1, "catalog_id": catalog_id(plan), "revision": revision,
             "generation": generation, "generated_at": now, "snapshot": public_snapshot(snapshot, plan)}
    return {**state, "build_id": digest(state)}


def validate_state(state, plan):
    require(set(state) == {"schema_version", "catalog_id", "revision", "generation", "generated_at", "snapshot", "build_id"},
            "unexpected state fields")
    require(state["schema_version"] == 1 and state["catalog_id"] == catalog_id(plan), "incompatible publication")
    validate_public_snapshot(state["snapshot"], plan)
    expected = make_state(state["snapshot"], plan, state["revision"], state["generation"], state["generated_at"])
    require(expected == state, "publication digest mismatch")
    require(len(canonical(state)) <= MAX_STATE_BYTES, "publication too large")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def fetch_public(filename, nonce):
    require(filename in {"state.json", "manifest.json"}, "unexpected public endpoint")
    require(re.fullmatch(r"[0-9a-zA-Z-]+", nonce) is not None, "invalid request nonce")
    # No credential is sent. Reject redirects, oversized bodies, and unknown endpoints.
    request = Request(BASE + filename + "?b=" + nonce, headers={"Cache-Control": "no-cache", "Accept": "application/json"})
    with build_opener(NoRedirect()).open(request, timeout=15) as response:
        raw = response.read(MAX_STATE_BYTES + 1)
    require(len(raw) <= MAX_STATE_BYTES, "public response too large")
    return json.loads(raw)


def manifest(state):
    sources = state["snapshot"]
    times = [sources[k].get("last_success_at") for k in ["issues", "project", "wix"]]
    oldest = min(times, key=timestamp) if all(times) else None
    return {"schema_version": 1, "build_id": state["build_id"], "generation": state["generation"],
            "revision": state["revision"], "generated_at": state["generated_at"],
            "last_success_at": oldest, "degraded": any(sources[k]["status"] != "ok" for k in ["issues", "project", "wix"])}


def validate_manifest(value):
    require(set(value) == {"schema_version", "build_id", "generation", "revision", "generated_at", "last_success_at", "degraded"},
            "unexpected manifest fields")
    require(value["schema_version"] == 1 and type(value["generation"]) is int and value["generation"] > 0,
            "invalid manifest version")
    require(isinstance(value["build_id"], str) and re.fullmatch(r"[0-9a-f]{64}", value["build_id"]), "invalid build ID")
    require(isinstance(value["revision"], str) and re.fullmatch(r"[0-9a-f]{40}", value["revision"]), "invalid revision")
    timestamp(value["generated_at"])
    if value["last_success_at"] is not None:
        timestamp(value["last_success_at"])
    require(type(value["degraded"]) is bool, "invalid degraded flag")


def audit_tree(output):
    output = Path(output)
    require(not output.is_symlink(), "symlinks cannot be published")
    actual = set()
    for path in output.rglob("*"):
        require(not path.is_symlink(), "symlinks cannot be published")
        if path.is_dir():
            require(path.relative_to(output).as_posix() == "assets", "unexpected publication directory")
        if path.is_file():
            require(path.stat().st_nlink == 1, "hard links cannot be published")
            actual.add(path.relative_to(output).as_posix())
    require(actual == FILES, "unexpected publication files")
    require(sum((output / name).stat().st_size for name in FILES) <= 2 * 1024 * 1024, "publication too large")


def write_site(output, state, plan, baselines):
    from build_dashboard import render
    validate_state(state, plan)
    output = Path(output)
    require(not output.is_symlink(), "output cannot be a symlink")
    require(not output.exists() or not any(output.iterdir()), "output must be a new empty directory")
    output.mkdir(parents=True, exist_ok=True)
    html = render(plan, state["snapshot"], baselines)
    require(html.count("</head>") == 1 and html.count("</main>") == 1 and html.count("</body>") == 1,
            "unsupported template structure")
    html = html.replace("</head>", f'<meta name="dashboard-version" content="{state["build_id"]}">'
                        f'<meta name="dashboard-generation" content="{state["generation"]}"></head>')
    html = html.replace("</main>", '<p id="auto-update-status" class="notice" role="status" hidden></p></main>')
    html = html.replace("</body>", f'<script src="assets/auto-refresh.js?v={state["build_id"]}" defer></script></body>')
    for name in ["index.html", "migration-dashboard.html"]:
        (output / name).write_text(html, encoding="utf-8")
    (output / "state.json").write_bytes(canonical(state))
    (output / "manifest.json").write_bytes(canonical(manifest(state)))
    (output / ".nojekyll").write_text("")
    (output / "assets").mkdir()
    (output / "assets/auto-refresh.js").write_bytes((ROOT / "assets/auto-refresh.js").read_bytes())
    audit_tree(output)
