from sentinel_api.domain import WorkProduct, WorkProductKind, plan_invalidation


def test_revision_change_invalidates_only_direct_and_transitive_dependants() -> None:
    evidence = WorkProduct(
        kind=WorkProductKind.RAW_EVIDENCE,
        output_key="evidence:supplier-a",
        request_revision_number=1,
        policy_revision=1,
        depends_on=frozenset({"source:https://supplier.example/item"}),
    )
    observation = WorkProduct(
        kind=WorkProductKind.OBSERVATION,
        output_key="observation:supplier-a:delivery",
        request_revision_number=1,
        policy_revision=1,
        depends_on=frozenset({"evidence:supplier-a", "requirement:delivery"}),
    )
    ranking = WorkProduct(
        kind=WorkProductKind.RANKING,
        output_key="ranking:lot-a",
        request_revision_number=1,
        policy_revision=1,
        depends_on=frozenset({"observation:supplier-a:delivery", "requirement:budget"}),
    )
    unrelated = WorkProduct(
        kind=WorkProductKind.RAW_EVIDENCE,
        output_key="evidence:supplier-b",
        request_revision_number=1,
        policy_revision=1,
        depends_on=frozenset({"source:https://other.example/item"}),
    )

    plan = plan_invalidation(
        (evidence, observation, ranking, unrelated),
        frozenset({"requirement:delivery"}),
    )

    invalidated_ids = {item.product_id for item in plan.invalidated}
    assert invalidated_ids == {observation.id, ranking.id}
    assert set(plan.retained_product_ids) == {evidence.id, unrelated.id}


def test_source_change_invalidates_evidence_and_all_dependants() -> None:
    evidence = WorkProduct(
        kind=WorkProductKind.RAW_EVIDENCE,
        output_key="evidence:a",
        request_revision_number=1,
        policy_revision=1,
        depends_on=frozenset({"source:a"}),
    )
    evaluation = WorkProduct(
        kind=WorkProductKind.EVALUATION,
        output_key="evaluation:a",
        request_revision_number=1,
        policy_revision=1,
        depends_on=frozenset({"evidence:a"}),
    )

    plan = plan_invalidation((evaluation, evidence), frozenset({"source:a"}))

    assert {item.product_id for item in plan.invalidated} == {evidence.id, evaluation.id}
    assert plan.retained_product_ids == ()
