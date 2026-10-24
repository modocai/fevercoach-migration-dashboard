"""Validated, public projections of migration evidence (Python stdlib only)."""
import json
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
STATES = {"todo", "doing", "done", "blocked", "unknown", "excluded"}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    path = Path(path)
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def timestamp(value):
    require(isinstance(value, str), "timestamp required")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(parsed.tzinfo is not None, "timestamp must include timezone")
    return parsed


def safe_url(value):
    if not isinstance(value, str):
        return False
    parsed = urlsplit(value)
    return (parsed.scheme == "https" and bool(parsed.hostname)
            and not parsed.username and not parsed.password
            and not any(ord(c) < 32 for c in value))


def validate_plan(plan):
    require(plan.get("schema_version") == 1, "unsupported plan schema")
    require(plan["repository"] == "modocai/fevercoach-website", "unexpected source repository")
    ids = [p["id"] for p in plan["phases"]]
    require(len(ids) == len(set(ids)) and ids == list(range(6)), "six unique phases required")
    numbers = [t["number"] for t in plan["tasks"]]
    require(len(numbers) == len(set(numbers)) and all(type(n) is int and n > 0 for n in numbers),
            "task numbers must be unique positive integers")
    for task in plan["tasks"]:
        require(task["phase"] in ids and bool(task["title"].strip()), "invalid task")
    require(set(plan["project"]["status_map"].values()) <= STATES, "invalid status mapping")
    for phase in plan["phases"]:
        for gate in phase.get("gates", []):
            require(set(gate["issues"]) <= set(numbers), "gate references unknown task")
            proof = gate["verification"]
            require(proof["status"] in {"pending", "passed", "failed"}, "invalid verification")
            if proof["status"] == "passed":
                require(safe_url(proof.get("url")), "passed gate requires evidence URL")
                timestamp(proof.get("checked_at"))
                require(bool(proof.get("reviewer")), "passed gate requires reviewer")
                if gate.get("approval"):
                    require(proof["reviewer"] == "MC", "MC approval must be recorded explicitly")


def project_issues(raw, plan):
    """Select only known issues. Never publish bodies, comments, or new private titles."""
    expected = {t["number"] for t in plan["tasks"]}
    selected = {}
    for issue in raw:
        number = issue.get("number")
        if "pull_request" in issue or number not in expected:
            continue
        require(number not in selected, "duplicate issue in response")
        require(issue.get("html_url") == f"https://github.com/{plan['repository']}/issues/{number}",
                "issue belongs to unexpected repository")
        require(issue["state"] in {"open", "closed"}, "invalid issue state")
        timestamp(issue["updated_at"])
        selected[number] = {"number": number, "state": issue["state"],
                            "state_reason": issue.get("state_reason"),
                            "assignees": [a["login"] for a in issue.get("assignees", [])],
                            "updated_at": issue["updated_at"]}
    require(set(selected) == expected, "incomplete issue response; previous snapshot retained")
    return [selected[n] for n in sorted(selected)]


def project_items(raw, plan):
    expected = {t["number"] for t in plan["tasks"]}
    selected = {}
    mapping = {k.casefold(): v for k, v in plan["project"]["status_map"].items()}
    for item in raw:
        content = item.get("content") or {}
        if (content.get("__typename") != "Issue"
                or content.get("repository", {}).get("nameWithOwner") != plan["repository"]
                or content.get("number") not in expected):
            continue
        number = content["number"]
        require(number not in selected, "duplicate project item")
        fields = {f.get("field", {}).get("name"): f for f in item["fieldValues"]["nodes"]}
        label = fields.get(plan["project"]["status_field"], {}).get("name")
        due = fields.get(plan["project"].get("due_date_field"), {}).get("date")
        if due:
            datetime.strptime(due, "%Y-%m-%d")
        selected[number] = {"number": number,
                            "status": mapping.get((label or "").casefold(), "unknown"),
                            "due_date": due}
    # Missing or inaccessible items remain unknown, not implicitly Todo.
    return [selected[n] for n in sorted(selected)]


def project_wix(raw):
    require(raw.get("schema_version") == 1, "unsupported Wix schema")
    require(raw.get("scope") == "public_sitemap_snapshot", "unexpected Wix scope")
    require(raw.get("source") == "https://www.fevercoach.us", "unexpected Wix source")
    timestamp(raw["generated_at"])
    counts = ["discovered_urls", "exported_urls", "unique_referenced_images", "downloaded_images",
              "images_not_downloaded_count", "failed_url_count", "missing_url_count", "media_error_count"]
    flags = ["all_discovered_urls_exported", "all_referenced_images_downloaded",
             "authoritative_wix_export_complete", "dns_zone_export_complete"]
    for key in counts:
        require(type(raw.get(key)) is int and raw[key] >= 0, f"invalid count: {key}")
    for key in flags:
        require(type(raw.get(key)) is bool, f"invalid flag: {key}")
    require(raw["exported_urls"] <= raw["discovered_urls"], "export exceeds discovered URLs")
    require(raw["downloaded_images"] + raw["images_not_downloaded_count"] == raw["unique_referenced_images"],
            "image inventory counts disagree")
    if raw["all_discovered_urls_exported"]:
        require(raw["exported_urls"] == raw["discovered_urls"] and raw["missing_url_count"] == 0
                and raw["failed_url_count"] == 0, "URL completion contradicts counts")
    if raw["all_referenced_images_downloaded"]:
        require(raw["images_not_downloaded_count"] == 0, "image completion contradicts counts")
    require(raw.get("media_download_scope") in {"sample", "full"}, "unknown media scope")
    # Explicit allowlist: no local paths, DNS answers, raw inventories, or private content.
    keys = counts + flags + ["schema_version", "scope", "source", "generated_at", "media_download_scope"]
    return {key: raw[key] for key in keys}


def task_states(plan, snapshot):
    issues = {i["number"]: i for i in snapshot.get("issues", {}).get("items", [])}
    project = {i["number"]: i for i in snapshot.get("project", {}).get("items", [])}
    rows = []
    for task in plan["tasks"]:
        issue = issues.get(task["number"])
        item = project.get(task["number"], {})
        board_state = item.get("status", "unknown")
        state, conflict = "unknown", False
        if issue:
            if issue["state"] == "closed" and issue.get("state_reason") == "completed":
                state = "done"
                conflict = board_state not in {"unknown", "done"}
            elif issue["state"] == "closed" and issue.get("state_reason") == "not_planned":
                state = "excluded"
                conflict = board_state == "done"
            elif issue["state"] == "open":
                state = board_state if board_state in {"todo", "doing", "blocked"} else "unknown"
                conflict = board_state in {"done", "excluded"}
        rows.append({**task, "status": state, "conflict": conflict,
                     "assignees": issue.get("assignees") if issue else None,
                     "due_date": item.get("due_date"),
                     "issue_known": issue is not None})
    return rows


def gate_state(gate, rows):
    states = {r["number"]: r for r in rows}
    if gate["verification"]["status"] == "failed":
        return "failed", "검증 실패"
    if any(states[n]["status"] != "done" or states[n]["conflict"] for n in gate["issues"]):
        return "pending", "관련 작업 완료 확인 필요"
    if gate["verification"]["status"] != "passed":
        return "pending", "MC 승인 근거 대기" if gate.get("approval") else "검증 근거 대기"
    return "passed", "근거 확인 완료"


def validate_baselines(data):
    require(data.get("schema_version") == 1, "unsupported baseline schema")
    targets = data["targets"]
    require(type(targets["performance"]) in {int, float} and 0 <= targets["performance"] <= 100,
            "invalid performance target")
    require(type(targets["lcp_seconds"]) in {int, float} and 0 < targets["lcp_seconds"] < float("inf"),
            "invalid LCP target")
    for record in data["lighthouse"]:
        require(record["kind"] in {"historical", "baseline", "staging"}, "invalid measurement kind")
        require(record["page"] in {"home", "post"}, "invalid measurement page")
        require(record["status"] in {"pending", "measured"}, "invalid measurement status")
        if record["status"] == "measured":
            require(safe_url(record["url"]) and safe_url(record["evidence_url"]), "measurement needs URLs")
            require(record.get("measured_on") and record.get("conditions"), "measurement needs date and conditions")
            datetime.strptime(record["measured_on"], "%Y-%m-%d")
            score, lcp = record["performance"], record["lcp_seconds"]
            require(type(score) in {int, float} and 0 <= score <= 100, "invalid Lighthouse score")
            require(type(lcp) in {int, float} and 0 <= lcp < float("inf"), "invalid LCP")
        else:
            require(record["performance"] is None and record["lcp_seconds"] is None,
                    "pending values must be null, not zero")
    for record in data["search_console"]:
        require(record["status"] in {"pending", "measured"}, "invalid Search Console status")
        if record["status"] == "measured":
            start = datetime.strptime(record["period_start"], "%Y-%m-%d")
            end = datetime.strptime(record["period_end"], "%Y-%m-%d")
            require((end - start).days == 27, "Search Console baseline must cover 28 inclusive days")
            require(safe_url(record["evidence_url"]), "Search Console needs evidence")
            for key in ["clicks", "impressions"]:
                require(type(record[key]) is int and record[key] >= 0, "invalid Search Console count")
        else:
            require(record["clicks"] is None and record["impressions"] is None, "pending counts must be null")


def validate_snapshot(snapshot, plan, *, sources=("issues", "project", "wix")):
    """Validate a complete snapshot, or one candidate source before replacing its cache."""
    require(snapshot.get("schema_version") == 1, "unsupported snapshot schema")
    require(set(snapshot) <= {"schema_version", "issues", "project", "wix"}, "unexpected snapshot fields")
    expected = {t["number"] for t in plan["tasks"]}
    common = {"status", "attempted_at", "last_success_at", "error"}
    require(bool(sources) and set(sources) <= {"issues", "project", "wix"}, "invalid source selection")
    for name in sources:
        section = snapshot[name]
        extra = {"items"} if name != "wix" else {"data", "source_sha", "source_url", "review_state", "pr_url"}
        require(set(section) <= common | extra, "unexpected public source fields")
        require(section["status"] in {"ok", "error"}, "invalid source status")
        timestamp(section["attempted_at"])
        if section.get("last_success_at"):
            timestamp(section["last_success_at"])
        if section["status"] == "ok":
            require(bool(section.get("last_success_at")), "successful source needs timestamp")
            require(section.get("error") is None, "successful source cannot contain an error")
        else:
            require(isinstance(section.get("error"), str) and bool(section["error"]), "failed source needs an error")
        has_record = section["status"] == "ok" or bool(section.get("last_success_at"))
        if has_record:
            require(extra <= set(section), "successful or cached source needs a complete payload")
        else:
            require(not section.get("items") and "data" not in section, "source data needs a successful collection record")
        items = section.get("items", [])
        require(isinstance(items, list) and all(isinstance(item, dict) for item in items), "invalid source items")
        numbers = [i["number"] for i in items]
        require(len(numbers) == len(set(numbers)) and set(numbers) <= expected, "invalid snapshot task IDs")
        if name == "issues":
            if section["status"] == "ok" or section.get("last_success_at"):
                require(set(numbers) == expected, "incomplete issue snapshot")
            for item in items:
                require({"number", "state", "state_reason"} <= set(item)
                        and set(item) <= {"number", "state", "state_reason", "assignees", "updated_at"},
                        "unexpected public issue fields")
                require(item["state"] in {"open", "closed"}, "invalid issue state")
                if "assignees" in item:
                    require(isinstance(item["assignees"], list) and all(isinstance(a, str) for a in item["assignees"]),
                            "invalid assignees")
                if "updated_at" in item:
                    timestamp(item["updated_at"])
        elif name == "project":
            for item in items:
                require(set(item) == {"number", "status", "due_date"}, "unexpected public Project fields")
                require(item["status"] in STATES, "invalid Project status")
                if item["due_date"]:
                    datetime.strptime(item["due_date"], "%Y-%m-%d")
        elif "data" in section:
            require(isinstance(section["data"], dict), "invalid Wix payload")
            require(project_wix(section["data"]) == section["data"], "unexpected public Wix fields")
            require(safe_url(section["source_url"]), "invalid Wix source URL")
            require(section["review_state"] in {"main", "open_pr"}, "invalid Wix review state")
            if section["review_state"] == "open_pr":
                require(section.get("pr_url") == "https://github.com/modocai/fevercoach-website/pull/29",
                        "unmerged Wix evidence must identify PR #29")
            require(len(section["source_sha"]) == 40 and all(c in '0123456789abcdef' for c in section["source_sha"]),
                    "invalid Wix source commit")
