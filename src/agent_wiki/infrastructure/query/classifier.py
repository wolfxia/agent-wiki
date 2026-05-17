from agent_wiki.domain.contracts import QueryClassifier


class RuleBasedQueryClassifier(QueryClassifier):
    def classify(self, query: str) -> str:
        lowered = query.lower()
        if any(token in lowered for token in ["proof", "evidence", "source"]):
            return "proof_trace"
        if any(token in lowered for token in ["compare", "tradeoff", "vs"]):
            return "compare_tradeoff"
        if any(token in lowered for token in ["why", "explain", "how"]):
            return "concept_explain"
        if any(token in lowered for token in ["trend", "scan"]):
            return "trend_scan"
        if any(token in lowered for token in ["should", "decision"]):
            return "decision_support"
        return "fact_lookup"


class LLMQueryClassifier(QueryClassifier):
    def classify(self, query: str) -> str:
        raise NotImplementedError("LLMQueryClassifier is reserved for future model-backed classification")
