from prd_to_readout.core.provenance import RunContext


def _ctx(**kw):
    base = dict(
        source_kind="file", n_control=2000, n_treatment=2000, required_n=1000,
        alpha=0.05, mde=0.05, multiple_comparison="Holm-Bonferroni", generated_at="2026-06-03",
    )
    base.update(kw)
    return RunContext(**base)


def test_simulated_is_never_trustworthy():
    ctx = _ctx(source_kind="simulated")
    assert ctx.is_simulated
    assert not ctx.trustworthy_verdict


def test_real_and_powered_is_trustworthy():
    assert _ctx().trustworthy_verdict


def test_underpowered_not_trustworthy():
    ctx = _ctx(n_control=100, n_treatment=100, required_n=1000)
    assert not ctx.powered
    assert not ctx.trustworthy_verdict


def test_no_required_n_counts_as_powered():
    assert _ctx(required_n=0).powered
