"""Optional Jira/GitHub REST adapters. No external writes during default demo.

The adapters are unit-tested using mock transports; live accounts have not been
verified. Writes are explicit CLI actions. No automatic mutation retry.
"""
import base64
import json
import re
import urllib.parse
import urllib.request
from .agents import NoRedirect


class RESTClient:
    def __init__(self, base, headers):
        parsed = urllib.parse.urlparse(base)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("external integrations require a credential-free HTTPS base URL")
        self.base, self.headers = base.rstrip("/"), headers

    def request(self, method, path, payload=None):
        request = urllib.request.Request(self.base + path,
                                         json.dumps(payload).encode() if payload is not None else None,
                                         headers={**self.headers, "Content-Type": "application/json"}, method=method)
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=30) as response:
            return json.load(response)


def adf(text):
    return {"type": "doc", "version": 1, "content": [{"type": "paragraph", "content": [
        {"type": "text", "text": text}]}]}


def flatten_adf(node):
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "\n".join(flatten_adf(x) for x in node)
    if isinstance(node, dict):
        return node.get("text", "") + flatten_adf(node.get("content", []))
    return ""


class JiraAdapter:
    def __init__(self, base, email, token, client=None):
        authorization = base64.b64encode((email + ":" + token).encode()).decode()
        self.client = client or RESTClient(base, {"Authorization": "Basic " + authorization, "Accept": "application/json"})

    def get_ticket(self, key, criteria):
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*-\d+", key):
            raise ValueError("invalid Jira issue key")
        item = self.client.request("GET", "/rest/api/3/issue/" + key)
        return {"key": item["key"], "source": "live-jira",
                "fields": {"summary": item["fields"]["summary"],
                           "description": flatten_adf(item["fields"].get("description")),
                           "acceptance_criteria": criteria}}

    def create_remediation(self, project, issue, issue_type="Task"):
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", project):
            raise ValueError("invalid Jira project")
        if not re.fullmatch(r"[A-Za-z0-9]{1,64}", issue["operation_key"]):
            raise ValueError("invalid operation key")
        # Attach a stable label for reconciliation. Caller must not blindly retry.
        label = "forgesdlc-" + issue["operation_key"]
        jql = f'project = {project} AND labels = "{label}"'
        existing = self.client.request("GET", "/rest/api/3/search/jql?" + urllib.parse.urlencode({"jql": jql, "fields": "summary"}))
        if existing.get("issues"):
            return {**existing["issues"][0], "reused": True}
        return self.client.request("POST", "/rest/api/3/issue", {"fields": {
            "project": {"key": project}, "issuetype": {"name": issue_type},
            "summary": issue["summary"], "description": adf(json.dumps(issue, indent=2)), "labels": [label]}})


class GitHubAdapter:
    def __init__(self, repository, token, client=None):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("repository must be owner/name")
        self.repository = repository
        self.client = client or RESTClient("https://api.github.com", {
            "Authorization": "Bearer " + token, "Accept": "application/vnd.github+json"})

    def create_pr(self, head, base, title, body, expected_sha, expected_base_sha=None):
        # Branch must already be pushed explicitly by the user.
        encoded_head = urllib.parse.quote(head, safe="")
        prefix = "/repos/" + self.repository
        commit = self.client.request("GET", prefix + "/commits/" + encoded_head)
        if commit.get("sha") != expected_sha:
            raise ValueError("remote branch SHA does not match locally verified candidate")
        if expected_base_sha is not None:
            base_commit = self.client.request("GET", prefix + "/commits/" + urllib.parse.quote(base, safe=""))
            if base_commit.get("sha") != expected_base_sha:
                raise ValueError("remote base SHA changed; reverify against the current base before publication")
        owner = self.repository.split("/")[0]
        query = urllib.parse.urlencode({"state": "open", "head": owner + ":" + head, "base": base})
        existing = self.client.request("GET", prefix + "/pulls?" + query)
        if existing:
            return {**existing[0], "reused": True}
        return self.client.request("POST", prefix + "/pulls", {
            "head": head, "base": base, "title": title, "body": body, "draft": True})
