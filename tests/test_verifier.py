from pathlib import Path

from repopilot.agents import VerifierAgent
from repopilot.models import Evidence, Finding, TaskState, VerificationStatus
from repopilot.tools import SafeFileReader


def make_state(repo: Path, evidence: list[Evidence], findings: list[Finding]) -> TaskState:
    return TaskState(
        repo_path=repo,
        question="Where is invoke_with_tools?",
        keywords=["invoke_with_tools"],
        evidence=evidence,
        findings=findings,
    )


def test_verifier_confirms_keyword_at_cited_lines(sample_repo: Path) -> None:
    """The keyword genuinely occurs in agent.py lines 1-5, so the citation is real."""
    evidence = [
        Evidence(
            path="agent.py",
            line_start=1,
            line_end=5,
            snippet="1: class ReActAgent:",
            keyword="invoke_with_tools",
        )
    ]
    state = make_state(
        sample_repo, evidence, [Finding(statement="x", evidence_ids=[evidence[0].id])]
    )

    result = VerifierAgent(reader=SafeFileReader()).run(state)

    assert result.verification[0].status == VerificationStatus.VERIFIED
    assert "keyword is present" in result.verification[0].reason


def test_verifier_rejects_fabricated_citation(sample_repo: Path) -> None:
    """A snippet claiming a line that does not contain the keyword is rejected."""
    evidence = [
        Evidence(
            path="agent.py",
            line_start=1,
            line_end=5,
            snippet="1: class ReActAgent:",
            keyword="totally_fake_symbol_xyz",
        )
    ]
    state = make_state(
        sample_repo, evidence, [Finding(statement="x", evidence_ids=[evidence[0].id])]
    )

    result = VerifierAgent(reader=SafeFileReader()).run(state)

    assert result.verification[0].status == VerificationStatus.REJECTED
    assert "absent from cited lines" in result.verification[0].reason


def test_verifier_without_reader_falls_back_to_existence_only(sample_repo: Path) -> None:
    """Without a reader the gate is the original existence check (backwards compatible)."""
    evidence = [
        Evidence(
            path="agent.py",
            line_start=1,
            line_end=5,
            snippet="1: class ReActAgent:",
            keyword="invoke_with_tools",
        )
    ]
    state = make_state(
        sample_repo, evidence, [Finding(statement="x", evidence_ids=[evidence[0].id])]
    )

    result = VerifierAgent().run(state)

    assert result.verification[0].status == VerificationStatus.VERIFIED
    assert "exists in the collected evidence set" in result.verification[0].reason


def test_verifier_rechecks_each_line_range_independently(sample_repo: Path) -> None:
    """Two citations of the same file must not share a cached read (cache-key regression)."""
    evidence = [
        Evidence(
            path="agent.py",
            line_start=1,
            line_end=5,
            snippet="1: class ReActAgent:",
            keyword="invoke_with_tools",
        ),
        Evidence(
            path="agent.py",
            line_start=4,
            line_end=5,
            snippet="4: if response == 'Finish':",
            keyword="invoke_with_tools",
        ),
    ]
    state = make_state(
        sample_repo,
        evidence,
        [
            Finding(statement="a", evidence_ids=[evidence[0].id]),
            Finding(statement="b", evidence_ids=[evidence[1].id]),
        ],
    )

    result = VerifierAgent(reader=SafeFileReader()).run(state)

    assert result.verification[0].status == VerificationStatus.VERIFIED  # lines 1-5 contain it
    assert result.verification[1].status == VerificationStatus.REJECTED  # lines 4-5 do not
