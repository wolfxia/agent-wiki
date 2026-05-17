from agent_wiki.domain.contracts import CompileSuggestionEvaluator, QualityEvaluator


class RuleBasedCompileSuggestionEvaluator(CompileSuggestionEvaluator):
    def evaluate(self, cluster: dict) -> dict:
        raw_count = cluster.get("raw_count", 0)
        return {
            **cluster,
            "should_suggest": raw_count >= 3,
        }


class RuleBasedQualityEvaluator(QualityEvaluator):
    def evaluate(self, inputs: dict) -> dict:
        return dict(inputs)
