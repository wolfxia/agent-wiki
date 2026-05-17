from agent_wiki.domain.contracts import CompileSuggestionEvaluator, QualityEvaluator
from agent_wiki.infrastructure.quality.evaluators import RuleBasedCompileSuggestionEvaluator, RuleBasedQualityEvaluator


def test_domain_exposes_quality_evaluator_protocols() -> None:
    assert getattr(CompileSuggestionEvaluator, "_is_protocol", False) is True
    assert getattr(QualityEvaluator, "_is_protocol", False) is True


def test_rule_based_quality_evaluators_are_default_implementations() -> None:
    compile_evaluator = RuleBasedCompileSuggestionEvaluator()
    quality_evaluator = RuleBasedQualityEvaluator()

    assert isinstance(compile_evaluator, CompileSuggestionEvaluator)
    assert isinstance(quality_evaluator, QualityEvaluator)
