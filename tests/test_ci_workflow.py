"""CI workflow must check out the repo without actions/checkout (org policy)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "test.yml"
GOLD_WORKFLOW = ROOT / ".github" / "workflows" / "request-gold-release.yml"


def test_ci_workflow_checks_out_with_plain_git():
    text = WORKFLOW.read_text(encoding="utf-8")
    # Must not *use* third-party checkout/setup actions (comments may name them).
    assert "uses: actions/checkout" not in text
    assert "uses: actions/setup-python" not in text
    assert "git fetch" in text
    assert "git checkout" in text
    assert "requirements-dev.txt" in text
    assert "pytest" in text
    # Must verify tree is present before pip install.
    assert text.index("Checkout repository") < text.index("Install dev dependencies")
    assert text.index("test -f requirements-dev.txt") < text.index(
        "Install dev dependencies"
    )


def test_gold_dispatch_defaults_to_nlpp_gold_maker():
    """Pings the real bake repo, not the old <owner>/nlpp-gold 404 slug."""
    text = GOLD_WORKFLOW.read_text(encoding="utf-8")
    assert 'GOLD="${{ github.repository_owner }}/nlpp-gold-maker"' in text
    assert "secrets.NLPP_GOLD_DISPATCH_TOKEN" in text
    assert 'GOLD="${{ github.repository_owner }}/nlpp-gold"' not in text
    assert "*/nlpp-gold)" in text
    assert "${GOLD%/nlpp-gold}/nlpp-gold-maker" in text
