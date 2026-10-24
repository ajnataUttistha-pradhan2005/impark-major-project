"""Core EvaluationService executing metric calculations and reporting."""

from uuid import uuid4

from evaluation.ground_truth import GroundTruthMatcher
from evaluation.metrics.claims import (
    ClaimEvaluator,
    NullClaimEvaluator,
    calculate_claim_metrics,
)
from evaluation.metrics.graph_precision import calculate_graph_precision
from evaluation.metrics.routing import calculate_routing_compliance
from evaluation.models import (
    CoverageSummary,
    EvaluationResult,
    EvaluationTurn,
    GroundTruthTestCase,
    MetricDiagnostic,
    TurnMetricResult,
)


class EvaluationService:
    """Orchestrates evaluation across matched turns and ground truth cases."""

    def __init__(self, claim_evaluator: ClaimEvaluator | None = None) -> None:
        self.claim_evaluator = claim_evaluator or NullClaimEvaluator()

    async def evaluate_batch(
        self,
        turns: list[EvaluationTurn],
        ground_truth: list[GroundTruthTestCase],
    ) -> EvaluationResult:
        """Run evaluation metrics across turns matched to ground-truth cases."""
        matched, unmatched_cases, unmatched_turns = GroundTruthMatcher.match(ground_truth, turns)

        total_cases = len(ground_truth)
        matched_count = len(matched)
        missing_count = len(unmatched_cases)
        incomplete_count = 0
        evaluated_count = 0
        skipped_count = 0

        turn_results: list[TurnMetricResult] = []
        global_diagnostics: list[MetricDiagnostic] = []

        total_claims_all = 0
        evaluable_claims_all = 0
        skipped_claims_all = 0

        # Handle missing ground-truth cases (must not disappear from denominator)
        for missing_case in unmatched_cases:
            diag = MetricDiagnostic(
                code="MISSING_TURN_FOR_CASE",
                message=(
                    f"Ground-truth case '{missing_case.case_id}' has no matching app_turn or run."
                ),
                details={"case_id": missing_case.case_id, "query_text": missing_case.query_text},
            )
            global_diagnostics.append(diag)
            turn_results.append(
                TurnMetricResult(
                    case_id=missing_case.case_id,
                    target_capability=missing_case.target_capability,
                    diagnostics=[diag],
                )
            )

        # Process matched turns
        routing_compliances: list[bool] = []
        graph_precisions: list[float] = []
        claim_groundedness_scores: list[float] = []
        claim_hallucination_scores: list[float] = []

        for case, turn in matched:
            # Check for incomplete turn
            if turn.status in {
                "MISSING_APP_TURN",
                "CORRUPT_STATE_JSON",
                "INVALID_STATE",
                "CORRUPT_STATE_PAYLOAD",
            }:
                incomplete_count += 1
                skipped_count += 1
                diag = MetricDiagnostic(
                    code="INCOMPLETE_TURN_SKIPPED",
                    message=f"Turn {turn.run_id} is incomplete ({turn.status}) and was skipped.",
                    details={"status": turn.status, "run_id": str(turn.run_id)},
                )
                turn_results.append(
                    TurnMetricResult(
                        run_id=turn.run_id,
                        session_id=turn.session_id,
                        case_id=case.case_id,
                        user_message_sample=turn.user_message[:120],
                        diagnostics=[*turn.diagnostics, diag],
                    )
                )
                continue

            evaluated_count += 1

            # 1. Routing Compliance
            routing_compliant, observed_path = calculate_routing_compliance(
                observed_path=turn.execution_path,
                target_capability=case.target_capability,
                disallowed_capabilities=case.disallowed_capabilities,
            )
            routing_compliances.append(routing_compliant)

            # 2. Graph Retrieval Precision
            retrieved_set = turn.canonical_node_set
            relevant_set = case.relevant_node_set
            prec_val, prec_diags = calculate_graph_precision(retrieved_set, relevant_set)
            if prec_val is not None:
                graph_precisions.append(prec_val)

            # 3. Claims Evaluation
            claim_eval_result = await self.claim_evaluator.evaluate_turn_claims(turn)
            (
                g_val,
                hr_val,
                tot_c,
                eval_c,
                sup_c,
                unsup_c,
                claim_diags,
            ) = calculate_claim_metrics(claim_eval_result)

            total_claims_all += tot_c
            evaluable_claims_all += eval_c
            skipped_claims_all += tot_c - eval_c

            if g_val is not None:
                claim_groundedness_scores.append(g_val)
            if hr_val is not None:
                claim_hallucination_scores.append(hr_val)

            all_turn_diags = [*turn.diagnostics, *prec_diags, *claim_diags]

            turn_results.append(
                TurnMetricResult(
                    run_id=turn.run_id,
                    session_id=turn.session_id,
                    case_id=case.case_id,
                    user_message_sample=turn.user_message[:120],
                    routing_compliant=routing_compliant,
                    target_capability=case.target_capability,
                    observed_path=observed_path,
                    graph_precision=prec_val,
                    retrieved_nodes_count=len(retrieved_set),
                    relevant_nodes_count=len(relevant_set),
                    retrieved_nodes=list(retrieved_set),
                    relevant_nodes=list(relevant_set),
                    groundedness=g_val,
                    hallucination_rate=hr_val,
                    total_claims_count=tot_c,
                    evaluable_claims_count=eval_c,
                    supported_claims_count=sup_c,
                    unsupported_claims_count=unsup_c,
                    diagnostics=all_turn_diags,
                )
            )

        # Coverage aggregation
        turn_coverage = evaluated_count / total_cases if total_cases > 0 else 0.0
        claim_coverage = evaluable_claims_all / total_claims_all if total_claims_all > 0 else 0.0

        coverage = CoverageSummary(
            total_cases=total_cases,
            matched_turns=matched_count,
            missing_turns=missing_count,
            incomplete_turns=incomplete_count,
            evaluated_turns=evaluated_count,
            skipped_turns=skipped_count,
            turn_coverage=round(turn_coverage, 4),
            total_claims=total_claims_all,
            evaluable_claims=evaluable_claims_all,
            skipped_claims=skipped_claims_all,
            claim_coverage=round(claim_coverage, 4),
        )

        # Calculate macro averages
        mean_routing = (
            sum(1.0 if c else 0.0 for c in routing_compliances) / len(routing_compliances)
            if routing_compliances
            else None
        )
        mean_precision = sum(graph_precisions) / len(graph_precisions) if graph_precisions else None
        mean_groundedness = (
            sum(claim_groundedness_scores) / len(claim_groundedness_scores)
            if claim_groundedness_scores
            else None
        )
        mean_hallucination = (
            sum(claim_hallucination_scores) / len(claim_hallucination_scores)
            if claim_hallucination_scores
            else None
        )

        return EvaluationResult(
            evaluation_id=uuid4(),
            routing_accuracy=round(mean_routing, 4) if mean_routing is not None else None,
            graph_precision=(round(mean_precision, 4) if mean_precision is not None else None),
            groundedness=(round(mean_groundedness, 4) if mean_groundedness is not None else None),
            hallucination_rate=(
                round(mean_hallucination, 4) if mean_hallucination is not None else None
            ),
            coverage=coverage,
            turn_results=turn_results,
            diagnostics=global_diagnostics,
            data_sources_used={
                "domain_trace": True,
                "app_turn": True,
                "ground_truth": True,
            },
        )
