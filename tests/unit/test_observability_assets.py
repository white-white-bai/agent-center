import json
from pathlib import Path

DASHBOARD = (
    Path(__file__).resolve().parents[2]
    / "deploy"
    / "observability"
    / "grafana"
    / "dashboards"
    / "agent-center-overview.json"
)


def test_grafana_dashboard_is_valid_and_links_exemplars() -> None:
    dashboard = json.loads(DASHBOARD.read_text(encoding="utf-8"))

    assert dashboard["uid"] == "agent-center-overview"
    assert len(dashboard["panels"]) >= 8
    targets = [
        target
        for panel in dashboard["panels"]
        for target in panel.get("targets", [])
    ]
    assert any(target.get("exemplar") for target in targets)
    assert any(
        panel.get("datasource", {}).get("uid") == "tempo" for panel in dashboard["panels"]
    )
