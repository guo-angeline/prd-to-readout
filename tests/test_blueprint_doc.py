from prd_to_readout.agents.hypothesis_agent import render_blueprint_doc


def test_blueprint_doc_has_friendly_sections(blueprint):
    md = render_blueprint_doc(blueprint)
    for section in ["# Analytics Blueprint:", "The bet", "Primary metric",
                    "Guardrails", "Health to watch", "How we will test it"]:
        assert section in md, section
    # readable content, not raw yaml keys
    assert blueprint.primary_metric.name in md
    assert "If we" in md and "Because" in md
    assert "—" not in md  # house style


def test_blueprint_doc_points_at_yaml_source(blueprint):
    md = render_blueprint_doc(blueprint)
    assert "analytics_blueprint.yaml" in md
