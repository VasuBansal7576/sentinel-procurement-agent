from sentinel_api.domain import AutonomyMode, autonomy_label, autonomy_policy_decision


def test_autonomy_labels_are_non_engineer_language() -> None:
    assert "Research only" in autonomy_label(AutonomyMode.RESEARCH_ONLY)
    assert "Ask before external" in autonomy_label(AutonomyMode.ASK_BEFORE_EXTERNAL)
    assert "Approve and hold" in autonomy_label(AutonomyMode.APPROVE_AND_HOLD)


def test_autonomy_policy_decisions_never_imply_auto_send() -> None:
    research = autonomy_policy_decision(AutonomyMode.RESEARCH_ONLY).lower()
    ask = autonomy_policy_decision(AutonomyMode.ASK_BEFORE_EXTERNAL).lower()
    hold = autonomy_policy_decision(AutonomyMode.APPROVE_AND_HOLD).lower()
    assert "disabled" in research
    assert "never sends" in ask
    assert "never auto-sends" in hold or "never happens" in hold
