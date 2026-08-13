from __future__ import annotations

import json
from dataclasses import dataclass

from repopilot.models import Evidence
from repopilot.runtime.models import AgentRun, AgentStep, ContextPhase, ContextTrace


@dataclass(frozen=True)
class ContextBuilder:
    """Deterministically pack useful Agent state into explicit character budgets."""

    max_history_steps: int = 8
    max_observation_chars: int = 1_600
    max_evidence_inventory: int = 12
    max_finalizer_evidence: int = 12
    max_evidence_snippet_chars: int = 800

    def build_decision(self, run: AgentRun) -> tuple[dict[str, object], ContextTrace]:
        budget = run.decision_context_chars
        context: dict[str, object] = {
            "question": run.question,
            "step_budget_remaining": run.max_steps - len(run.steps),
            "collected_evidence": [],
            "recent_history": [],
        }
        truncated_items = 0
        if self._size(context) > budget:
            # Questions may contain long logs. Preserve the beginning and make truncation visible.
            fixed_overhead = self._size({**context, "question": ""})
            allowed = max(200, budget - fixed_overhead - 600)
            context["question"] = run.question[:allowed]
            truncated_items += 1

        inventory: list[dict[str, object]] = []
        for evidence in reversed(run.evidence[-self.max_evidence_inventory :]):
            item, was_truncated = self._inventory_item(evidence)
            candidate_inventory = [item, *inventory]
            candidate = {**context, "collected_evidence": candidate_inventory}
            # Keep room for at least one compact recent observation.
            if self._size(candidate) > budget - 500:
                break
            inventory.insert(0, item)
            truncated_items += int(was_truncated)
        context["collected_evidence"] = inventory

        selected: list[dict[str, object]] = []
        candidates = run.steps[-self.max_history_steps :]
        for step in reversed(candidates):
            item, was_truncated = self._history_item(step)
            candidate_history = [item, *selected]
            candidate = {**context, "recent_history": candidate_history}
            if self._size(candidate) <= budget:
                selected.insert(0, item)
                truncated_items += int(was_truncated)
                continue
            if not selected:
                compact = {**item, "observation": str(item["observation"])[:300]}
                candidate = {**context, "recent_history": [compact]}
                if self._size(candidate) <= budget:
                    selected.insert(0, compact)
                    truncated_items += 1
            break
        context["recent_history"] = selected
        included_indexes = [int(item["step"]) for item in selected]
        trace = ContextTrace(
            phase=ContextPhase.DECISION,
            char_budget=budget,
            chars_used=self._size(context),
            steps_available=len(run.steps),
            step_indexes_included=included_indexes,
            steps_dropped=max(0, len(run.steps) - len(included_indexes)),
            evidence_available=len(run.evidence),
            evidence_ids_included=[item["id"] for item in inventory],
            evidence_dropped=max(0, len(run.evidence) - len(inventory)),
            truncated_items=truncated_items,
        )
        return context, trace

    def build_finalizer(self, run: AgentRun) -> tuple[dict[str, object], ContextTrace]:
        budget = run.finalizer_context_chars
        selected: list[dict[str, object]] = []
        selected_ids: list[str] = []
        truncated_items = 0
        context: dict[str, object] = {
            "instruction": "Finalize the answer as JSON now.",
            "question": run.question,
            "evidence": selected,
        }
        if self._size(context) > budget:
            fixed_overhead = self._size({**context, "question": ""})
            allowed = max(200, budget - fixed_overhead - (800 if run.evidence else 100))
            context["question"] = run.question[:allowed]
            truncated_items += 1

        for evidence in self._prioritized_evidence(run):
            item, was_truncated = self._evidence_item(evidence)
            candidate = {**context, "evidence": [*selected, item]}
            if self._size(candidate) > budget:
                continue
            selected.append(item)
            selected_ids.append(evidence.id)
            truncated_items += int(was_truncated)
            if len(selected) >= self.max_finalizer_evidence:
                break
        if not selected and run.evidence:
            evidence = self._prioritized_evidence(run)[0]
            item, _ = self._evidence_item(evidence, snippet_chars=200)
            candidate = {**context, "evidence": [item]}
            if self._size(candidate) > budget:
                overrun = self._size(candidate) - budget
                question = str(context["question"])
                context["question"] = question[: max(200, len(question) - overrun - 20)]
                truncated_items += 1
                candidate = {**context, "evidence": [item]}
            if self._size(candidate) <= budget:
                selected.append(item)
                selected_ids.append(evidence.id)
                truncated_items += 1
        context["evidence"] = selected
        trace = ContextTrace(
            phase=ContextPhase.FINALIZER,
            char_budget=budget,
            chars_used=self._size(context),
            steps_available=len(run.steps),
            step_indexes_included=[],
            steps_dropped=len(run.steps),
            evidence_available=len(run.evidence),
            evidence_ids_included=selected_ids,
            evidence_dropped=max(0, len(run.evidence) - len(selected_ids)),
            truncated_items=truncated_items,
        )
        return context, trace

    def _inventory_item(self, item: Evidence) -> tuple[dict[str, object], bool]:
        compact = {
            "id": item.id[:100],
            "citation": item.citation[:300],
            "keyword": item.keyword[:120],
            "source": item.source[:80],
        }
        truncated = (
            compact["id"] != item.id
            or compact["citation"] != item.citation
            or compact["keyword"] != item.keyword
            or compact["source"] != item.source
        )
        return compact, truncated

    def _history_item(self, step: AgentStep) -> tuple[dict[str, object], bool]:
        content = step.observation.content
        truncated = len(content) > self.max_observation_chars
        return (
            {
                "step": step.index,
                "tool": step.decision.tool_name,
                "arguments": {
                    key: value
                    for key, value in step.decision.arguments.items()
                    if key != "reason"
                },
                "status": step.status.value,
                "observation": content[: self.max_observation_chars],
                "evidence_ids": [item.id for item in step.observation.evidence[:10]],
            },
            truncated,
        )

    def _prioritized_evidence(self, run: AgentRun) -> list[Evidence]:
        ordered = [
            *reversed([item for item in run.evidence if item.source == "agent_read_file"]),
            *[item for item in run.evidence if item.source != "agent_read_file"],
        ]
        seen: set[tuple[str, int, int]] = set()
        unique: list[Evidence] = []
        for item in ordered:
            key = (item.path, item.line_start, item.line_end)
            if key not in seen:
                seen.add(key)
                unique.append(item)
        return unique

    def _evidence_item(
        self, item: Evidence, snippet_chars: int | None = None
    ) -> tuple[dict[str, object], bool]:
        limit = snippet_chars or self.max_evidence_snippet_chars
        return (
            {
                "id": item.id[:100],
                "citation": item.citation[:300],
                "keyword": item.keyword[:120],
                "source": item.source[:80],
                "snippet": item.snippet[:limit],
            },
            (
                len(item.id) > 100
                or len(item.citation) > 300
                or len(item.keyword) > 120
                or len(item.source) > 80
                or len(item.snippet) > limit
            ),
        )

    @staticmethod
    def _size(value: object) -> int:
        return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
