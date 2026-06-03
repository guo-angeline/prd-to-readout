"""GitHub-native gates via the `gh` CLI.

Each gated stage becomes a GitHub Issue assigned to the declared approver. The
approver clears it by commenting `/approve` (or closing the issue) and sends it
back with `/request-changes <reason>`. `sync` polls these issues and reconciles
the local workflow state, so GitHub is the system of record and audit trail with
no hosted service to run.

All GitHub access goes through the `gh` CLI, which the user has already
authenticated. `evaluate_issue` is pure so the decision logic is unit-tested.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field

# Which approver role clears each gate.
GATE_ROLE = {
    "hypothesis": "product",
    "instrumentation": "engineering",
    "instrumentation_qa": "data_science",
    "pipeline": "data_science",
}
ROLES = ["product", "engineering", "data_science"]


class GitHubError(RuntimeError):
    """A `gh` invocation failed (not installed, not authed, or API error)."""


def _gh(args: list[str], *, input: str | None = None) -> str:
    try:
        r = subprocess.run(["gh", *args], input=input, capture_output=True, text=True)
    except FileNotFoundError as e:
        raise GitHubError("GitHub CLI 'gh' not found. Install it and run 'gh auth login'.") from e
    if r.returncode != 0:
        raise GitHubError(r.stderr.strip() or f"gh {' '.join(args)} failed")
    return r.stdout


@dataclass
class IssueComment:
    author: str
    body: str


@dataclass
class IssueState:
    number: int
    state: str  # "open" | "closed"
    comments: list[IssueComment] = field(default_factory=list)
    closed_by: str = ""  # login of whoever closed it (REST issues exposes this)


def evaluate_issue(issue: IssueState, approver: str) -> tuple[str, str | None]:
    """Decide a gate from issue activity. Returns (decision, note).

    decision in {"approved", "changes_requested", "pending"}. Approval requires a
    NAMED approver: only that approver's latest `/approve` or `/request-changes`
    comment counts, and a closed issue clears the gate only if the approver is the
    one who closed it. With no approver configured, the gate never auto-advances.
    """
    handle = approver.lstrip("@").lower()
    if not handle:
        return "pending", None  # no named approver: never auto-approve via GitHub
    for c in reversed(issue.comments):
        if c.author.lower() != handle:
            continue
        body = c.body.strip()
        low = body.lower()
        if low.startswith("/approve"):
            return "approved", None
        if low.startswith("/request-changes"):
            return "changes_requested", body[len("/request-changes"):].strip() or "changes requested"
    if issue.state == "closed" and issue.closed_by.lstrip("@").lower() == handle:
        return "approved", "issue closed by approver"
    return "pending", None


class GitHubClient:
    def __init__(self, repo: str):
        self.repo = repo  # "owner/name"

    # -- account / repo --------------------------------------------------- #
    @staticmethod
    def whoami() -> str:
        return _gh(["api", "user", "--jq", ".login"]).strip()

    @staticmethod
    def create_private_repo(name: str) -> str:
        """Create a new private repo. Returns 'owner/name'."""
        _gh(["repo", "create", name, "--private"])
        if "/" in name:
            return name
        return f"{GitHubClient.whoami()}/{name}"

    def user_exists(self, handle: str) -> bool:
        try:
            _gh(["api", f"users/{handle.lstrip('@')}"])
            return True
        except GitHubError:
            return False

    def add_collaborator(self, handle: str, permission: str = "push") -> None:
        _gh(["api", "--method", "PUT",
             f"repos/{self.repo}/collaborators/{handle.lstrip('@')}",
             "-f", f"permission={permission}"])

    # -- issues ----------------------------------------------------------- #
    def create_issue(self, title: str, body: str, assignee: str | None = None) -> tuple[int, str]:
        args = ["issue", "create", "--repo", self.repo, "--title", title, "--body-file", "-"]
        if assignee:
            args += ["--assignee", assignee.lstrip("@")]
        try:
            url = _gh(args, input=body).strip().splitlines()[-1]
        except GitHubError:
            # Assignee may not be a collaborator yet; fall back to an unassigned issue.
            url = _gh(["issue", "create", "--repo", self.repo, "--title", title, "--body-file", "-"],
                      input=body).strip().splitlines()[-1]
        number = int(url.rstrip("/").split("/")[-1])
        return number, url

    def get_issue(self, number: int) -> IssueState:
        out = _gh(["issue", "view", str(number), "--repo", self.repo, "--json", "number,state,comments"])
        d = json.loads(out)
        comments = [IssueComment((c.get("author") or {}).get("login", ""), c.get("body", ""))
                    for c in d.get("comments", [])]
        state = str(d["state"]).lower()
        closed_by = ""
        if state == "closed":
            # gh issue view doesn't expose the closer; the REST issues endpoint does.
            closed_by = _gh(["api", f"repos/{self.repo}/issues/{number}",
                             "--jq", '.closed_by.login // ""']).strip()
        return IssueState(d["number"], state, comments, closed_by=closed_by)

    def close_issue(self, number: int, comment: str | None = None) -> None:
        args = ["issue", "close", str(number), "--repo", self.repo]
        if comment:
            args += ["-c", comment]
        _gh(args)
