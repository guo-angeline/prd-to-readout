from typer.testing import CliRunner

from prd_to_readout import cli
from prd_to_readout.adapters import github
from prd_to_readout.adapters.github import IssueComment, IssueState, evaluate_issue
from prd_to_readout.cli import app
from prd_to_readout.config import Config
from prd_to_readout.core.schemas import Approvers
from prd_to_readout.core.state import WorkflowState

runner = CliRunner()


# --------------------------------------------------------------------------- #
# evaluate_issue: the pure decision logic
# --------------------------------------------------------------------------- #
def _issue(state="open", comments=(), closed_by=""):
    return IssueState(1, state, [IssueComment(a, b) for a, b in comments], closed_by=closed_by)


def test_approve_comment_by_approver():
    decision, _ = evaluate_issue(_issue(comments=[("carol", "/approve")]), "carol")
    assert decision == "approved"


def test_request_changes_carries_note():
    decision, note = evaluate_issue(_issue(comments=[("carol", "/request-changes wrong grain")]), "carol")
    assert decision == "changes_requested"
    assert note == "wrong grain"


def test_comment_by_someone_else_is_ignored():
    decision, _ = evaluate_issue(_issue(comments=[("rando", "/approve")]), "carol")
    assert decision == "pending"


def test_handle_match_is_case_insensitive_and_at_tolerant():
    decision, _ = evaluate_issue(_issue(comments=[("Carol", "/approve")]), "@carol")
    assert decision == "approved"


def test_latest_decision_wins():
    decision, _ = evaluate_issue(
        _issue(comments=[("carol", "/request-changes nope"), ("carol", "/approve")]), "carol")
    assert decision == "approved"


def test_closed_by_approver_counts_as_approved():
    decision, _ = evaluate_issue(_issue(state="closed", closed_by="carol"), "carol")
    assert decision == "approved"


def test_closed_by_someone_else_does_not_approve():
    decision, _ = evaluate_issue(_issue(state="closed", closed_by="rando"), "carol")
    assert decision == "pending"


def test_empty_approver_never_auto_approves():
    # No named approver: neither a closed issue nor a stray /approve advances the gate.
    assert evaluate_issue(_issue(state="closed", closed_by="rando"), "")[0] == "pending"
    assert evaluate_issue(_issue(comments=[("rando", "/approve")]), "")[0] == "pending"


# --------------------------------------------------------------------------- #
# fake client for CLI tests
# --------------------------------------------------------------------------- #
class FakeGH:
    def __init__(self, repo="owner/repo"):
        self.repo = repo
        self.created = []
        self.closed = []
        self.collabs = []
        self.issue_to_return = None

    @staticmethod
    def whoami():
        return "owner"

    @staticmethod
    def create_private_repo(name):
        return name if "/" in name else f"owner/{name}"

    def user_exists(self, handle):
        return True

    def add_collaborator(self, handle, permission="push"):
        self.collabs.append(handle)

    def create_issue(self, title, body, assignee=None):
        n = len(self.created) + 1
        self.created.append({"title": title, "assignee": assignee})
        return n, f"https://github.com/{self.repo}/issues/{n}"

    def get_issue(self, number):
        return self.issue_to_return

    def close_issue(self, number, comment=None):
        self.closed.append(number)


# --------------------------------------------------------------------------- #
# gate issue creation, sync, gh-setup, approver resolution
# --------------------------------------------------------------------------- #
def test_finish_stage_opens_issue_when_github_configured(tmp_path, blueprint, monkeypatch):
    cfg = Config.load(workdir=tmp_path)
    cfg.paths.ensure()
    cfg.paths.blueprint.write_text(blueprint.to_yaml())
    state = WorkflowState.new("feat")
    state.github = {"repo": "owner/repo", "approvers": {"product": "alice"}}
    fake = FakeGH()
    monkeypatch.setattr(cli, "_github_client", lambda s: fake)

    cli._finish_stage(cfg, state, "hypothesis", [cfg.paths.blueprint])
    assert state.stage("hypothesis").issue_number == 1
    assert fake.created[0]["assignee"] == "alice"


def test_no_github_means_no_issue(tmp_path, blueprint):
    cfg = Config.load(workdir=tmp_path)
    cfg.paths.ensure()
    state = WorkflowState.new("feat")  # github is None
    cli._finish_stage(cfg, state, "hypothesis", [cfg.paths.blueprint])
    assert state.stage("hypothesis").issue_number is None


def test_sync_approves_gate_from_issue(tmp_path, monkeypatch):
    cfg = Config.load(workdir=tmp_path)
    cfg.paths.ensure()
    state = WorkflowState.new("feat")
    state.github = {"repo": "owner/repo", "approvers": {"data_science": "carol"}}
    st = state.stage("pipeline")
    st.status = "awaiting_approval"
    st.issue_number = 7
    state.save(cfg.paths.state)

    fake = FakeGH()
    fake.issue_to_return = IssueState(7, "open", [IssueComment("carol", "/approve")])
    monkeypatch.setattr(cli, "_github_client", lambda s: fake)

    res = runner.invoke(app, ["sync", "-w", str(tmp_path)])
    assert res.exit_code == 0, res.stdout
    reloaded = WorkflowState.load(cfg.paths.state)
    assert reloaded.stage("pipeline").status == "approved"
    assert reloaded.stage("pipeline").approver == "carol"
    assert 7 in fake.closed


def test_gh_setup_creates_repo_and_invites(tmp_path, blueprint, monkeypatch):
    cfg = Config.load(workdir=tmp_path)
    cfg.paths.ensure()
    blueprint.approvers = Approvers(product="alice", engineering="bob", data_science="carol")
    cfg.paths.blueprint.write_text(blueprint.to_yaml())
    WorkflowState.new("feat").save(cfg.paths.state)

    monkeypatch.setattr(github, "GitHubClient", FakeGH)

    res = runner.invoke(app, ["gh-setup", "--repo", "my-launch", "-w", str(tmp_path)])
    assert res.exit_code == 0, res.stdout
    state = WorkflowState.load(cfg.paths.state)
    assert state.github["repo"] == "owner/my-launch"
    assert state.github["approvers"]["data_science"] == "carol"


def test_resolve_approvers_prompts_for_missing(tmp_path, blueprint, monkeypatch):
    state = WorkflowState.new("feat")  # no github
    blueprint.approvers = Approvers(product="alice", engineering="", data_science="carol")
    prompts = iter(["bob"])  # only engineering is missing
    monkeypatch.setattr(cli.typer, "prompt", lambda *a, **k: next(prompts))
    out = cli._resolve_approvers(blueprint, state, interactive=True)
    assert out == {"product": "alice", "engineering": "bob", "data_science": "carol"}
