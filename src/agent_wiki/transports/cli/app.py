from pathlib import Path
import os
import signal

import json

import typer

from agent_wiki.application.approvals import ApprovalService
from agent_wiki.application.capture_raw import CaptureRawService
from agent_wiki.application.compile_prepare import CompilePrepareInput, CompilePrepareService
from agent_wiki.application.compile_update import CompileUpdateService
from agent_wiki.application.feedback import FeedbackInput, FeedbackService
from agent_wiki.application.linting import LintService
from agent_wiki.application.maintenance import MaintenanceService
from agent_wiki.application.migration import NormalizeDocIdsMigration, SlugifyDocIdsMigration
from agent_wiki.application.quality_report import QualityReportService
from agent_wiki.application.query import QueryService
from agent_wiki.application.sync import SyncInput, SyncService
from agent_wiki.application.weekly_review import WeeklyReviewService
from agent_wiki.bootstrap.container import Container
from agent_wiki.bootstrap.registry_loader import RegistryLoader, WikiConfig
from agent_wiki.domain.contracts import ResolvedActor
from agent_wiki.domain.models import CaptureRawInput, CompileUpdateInput, IdentityContext, ProposalInput, QueryInput
from agent_wiki.infrastructure.identity.resolver import IdentityResolver
from agent_wiki.infrastructure.retrieval.index_consistency import IndexConsistencyChecker
from agent_wiki.infrastructure.runtime.review_queue import ReviewQueueRepository
from agent_wiki.settings import DEFAULT_REGISTRY_PATH
from agent_wiki.transports.errors import map_exception
from agent_wiki.transports.errors import error_payload
from agent_wiki.transports.mcp.server import MCPServer, run_stdio_server

app = typer.Typer(help="Agent Wiki CLI")
sync_app = typer.Typer(help="Sync workspace and external views")
approvals_app = typer.Typer(help="Manage approval proposals")
app.add_typer(sync_app, name="sync")
app.add_typer(approvals_app, name="approvals")

_DEFAULT_CLI_TIMEOUT_SECONDS = 300


def _raise_cli_timeout(signum: int, frame: object) -> None:
    raise TimeoutError(f"CLI command timed out after {_cli_timeout_seconds()} seconds")


def _cli_timeout_seconds() -> int:
    value = os.environ.get("AGENT_WIKI_CLI_TIMEOUT_SECONDS")
    if value is None:
        return _DEFAULT_CLI_TIMEOUT_SECONDS
    try:
        return int(value)
    except ValueError:
        return _DEFAULT_CLI_TIMEOUT_SECONDS


def _resolve_registry_path(registry: str | None) -> Path:
    return Path(registry or os.environ.get("AGENT_WIKI_REGISTRY") or DEFAULT_REGISTRY_PATH)


def _load_wiki(registry: str | None, workspace: str | None, wiki_id: str | None) -> WikiConfig:
    registry_config = RegistryLoader().load(_resolve_registry_path(registry))
    if wiki_id is None:
        wiki = registry_config.wikis[0]
    else:
        wiki = next((candidate for candidate in registry_config.wikis if candidate.wiki_id == wiki_id), None)
        if wiki is None:
            raise typer.BadParameter(f"unknown wiki_id: {wiki_id}")
    if workspace:
        wiki = wiki.model_copy(update={"workspace_path": workspace})
    return wiki


def _run_cli(action) -> None:
    try:
        action()
    except Exception as exc:
        typer.echo(json.dumps(error_payload(exc), ensure_ascii=False, separators=(",", ":")))
        raise typer.Exit(code=1) from exc


def _actor() -> ResolvedActor:
    return IdentityResolver().resolve(
        IdentityContext(
            transport="cli",
            actor_type=os.environ.get("AGENT_WIKI_ACTOR_TYPE"),
            actor_id=os.environ.get("AGENT_WIKI_ACTOR_ID"),
        )
    )


@app.callback()
def main_callback() -> None:
    """Agent Wiki CLI root."""


@app.command("info")
def info() -> None:
    container = Container()
    typer.echo(f"agent-wiki ready: {container.__class__.__name__}")


@app.command("health")
def health(
    workspace: str | None = typer.Option(None, "--workspace"),
    registry: str | None = typer.Option(None, "--registry"),
) -> None:
    def _command() -> None:
        registry_path = _resolve_registry_path(registry)
        registry_config = RegistryLoader().load(registry_path)
        wiki_count = len(registry_config.wikis)
        if wiki_count == 0:
            raise ValueError("registry must contain at least one wiki")

        index_issues: list[str] = []
        if workspace:
            wiki = _load_wiki(registry, workspace, None)
            index_issues = IndexConsistencyChecker().check(Path(wiki.workspace_path))

        actor = _actor()
        tools = MCPServer(registry_path=str(registry_path)).list_tools()
        typer.echo("status=ok")
        typer.echo(f"registry_path={registry_path}")
        typer.echo(f"wiki_count={wiki_count}")
        typer.echo(f"tool_count={len(tools)}")
        typer.echo(f"actor_type={actor.actor_type}")
        typer.echo(f"actor_id={actor.actor_id}")
        typer.echo(f"index_consistency={'fail' if index_issues else 'ok'}")
        for issue in index_issues:
            typer.echo(f"index_issue={issue}")

    _run_cli(_command)


@app.command("serve")
def serve(
    workspace: str | None = typer.Option(None, "--workspace"),
    registry: str | None = typer.Option(None, "--registry"),
) -> None:
    """Start the long-running agent-wiki MCP stdio service."""
    # The SIGALRM timer set in main() will kill the process after 300s.
    # `serve` is a long-running daemon — cancel the timer immediately.
    signal.alarm(0)
    if workspace:
        os.environ["AGENT_WIKI_WORKSPACE"] = workspace
    run_stdio_server(registry_path=registry)


@app.command("query")
def query(
    text: str = typer.Argument(..., help="Query text"),
    workspace: str | None = typer.Option(None, "--workspace"),
    registry: str | None = typer.Option(None, "--registry"),
    wiki_id: str | None = typer.Option(None, "--wiki-id"),
) -> None:
    def _command() -> None:
        wiki = _load_wiki(registry, workspace, wiki_id)
        result = QueryService().execute(wiki=wiki, actor=_actor(), data=QueryInput(query=text))
        typer.echo(f"hit_count={result.hit_count}")
        typer.echo(f"l1_answer={result.l1_answer}")
        for hit in result.hits:
            typer.echo(f"  hit: {hit.doc_id} score={hit.score}")

    _run_cli(_command)


@app.command("capture-raw")
def capture_raw(
    doc_id: str = typer.Argument(...),
    topic: str = typer.Option(...),
    problem_cluster: str = typer.Option(...),
    content: str = typer.Option(...),
    workspace: str | None = typer.Option(None, "--workspace"),
    registry: str | None = typer.Option(None, "--registry"),
    wiki_id: str | None = typer.Option(None, "--wiki-id"),
) -> None:
    def _command() -> None:
        wiki = _load_wiki(registry, workspace, wiki_id)
        result = CaptureRawService().execute(
            wiki=wiki, actor=_actor(),
            data=CaptureRawInput(
                doc_id=doc_id, topic=topic, problem_cluster=problem_cluster,
                content=content, source_refs=[],
            ),
        )
        typer.echo(f"status={result.status} doc_id={result.doc_id}")

    _run_cli(_command)


@app.command("compile-update")
def compile_update(
    doc_id: str = typer.Argument(...),
    page_type: str = typer.Option(...),
    topic: str = typer.Option(...),
    problem_cluster: str = typer.Option(...),
    content: str = typer.Option(...),
    source_refs: str = typer.Option("", help="Comma-separated source_refs"),
    summary: str | None = typer.Option(None, "--summary"),
    aliases: str = typer.Option("", "--aliases", help="Comma-separated aliases"),
    confidence: str | None = typer.Option(None, "--confidence"),
    contested: bool = typer.Option(False, "--contested"),
    wikilinks: str = typer.Option("", "--wikilinks", help="Comma-separated wikilinks"),
    sensitivity: str | None = typer.Option(None, "--sensitivity"),
    workspace: str | None = typer.Option(None, "--workspace"),
    registry: str | None = typer.Option(None, "--registry"),
    wiki_id: str | None = typer.Option(None, "--wiki-id"),
) -> None:
    def _command() -> None:
        wiki = _load_wiki(registry, workspace, wiki_id)
        refs = [r.strip() for r in source_refs.split(",") if r.strip()]
        alias_list = [item.strip() for item in aliases.split(",") if item.strip()]
        wikilink_list = [item.strip() for item in wikilinks.split(",") if item.strip()]
        result = CompileUpdateService().apply(
            wiki=wiki, actor=_actor(),
            data=CompileUpdateInput(
                doc_id=doc_id, page_type=page_type, topic=topic,
                problem_cluster=problem_cluster, summary=summary, aliases=alias_list,
                confidence=confidence, contested=contested, wikilinks=wikilink_list,
                sensitivity=sensitivity, content=content, source_refs=refs,
            ),
        )
        typer.echo(f"status={result.status} doc_id={result.doc_id}")

    _run_cli(_command)


@app.command("compile-prepare")
def compile_prepare(
    topic: str = typer.Option(..., "--topic"),
    problem_cluster: str = typer.Option(..., "--problem-cluster"),
    doc_ids: list[str] = typer.Option(None, "--doc-id"),
    max_items: int = typer.Option(8, "--max-items"),
    sub_cluster_index: int = typer.Option(1, "--sub-cluster-index"),
    workspace: str | None = typer.Option(None, "--workspace"),
    registry: str | None = typer.Option(None, "--registry"),
    wiki_id: str | None = typer.Option(None, "--wiki-id"),
) -> None:
    def _command() -> None:
        wiki = _load_wiki(registry, workspace, wiki_id)
        result = CompilePrepareService().prepare(
            wiki=wiki,
            actor=_actor(),
            data=CompilePrepareInput(
                topic=topic,
                problem_cluster=problem_cluster,
                doc_ids=doc_ids or None,
                max_items=max_items,
                sub_cluster_index=sub_cluster_index,
            ),
        )
        typer.echo(f"agent_objective={result.agent_objective}")
        typer.echo(f"sub_cluster_id={result.sub_cluster_id}")
        typer.echo(f"proposed_page_type={result.proposed_page_type}")
        typer.echo(f"proposed_doc_id={result.proposed_doc_id}")
        typer.echo(f"total_raw_count={result.total_raw_count}")
        for item in result.items:
            typer.echo(f"source_ref={item.source_ref} doc_id={item.doc_id}")

    _run_cli(_command)


@app.command("review-queue-consume")
def review_queue_consume(
    item_type: str = typer.Option(..., "--item-type"),
    workspace: str | None = typer.Option(None, "--workspace"),
    registry: str | None = typer.Option(None, "--registry"),
    wiki_id: str | None = typer.Option(None, "--wiki-id"),
) -> None:
    def _command() -> None:
        wiki = _load_wiki(registry, workspace, wiki_id)
        actor = _actor()
        item = ReviewQueueRepository(Path(wiki.workspace_path)).consume(item_type, actor.actor_id)
        if item is None:
            typer.echo("item_id=")
            return
        typer.echo(
            f"item_id={item.get('item_id')} status={item.get('status')} assigned_to={item.get('assigned_to')}"
        )

    _run_cli(_command)


@app.command("lint")
def lint(
    workspace: str | None = typer.Option(None, "--workspace"),
    registry: str | None = typer.Option(None, "--registry"),
    wiki_id: str | None = typer.Option(None, "--wiki-id"),
) -> None:
    def _command() -> None:
        wiki = _load_wiki(registry, workspace, wiki_id)
        result = LintService().run(wiki)
        if result.ok:
            typer.echo("ok: no issues")
        else:
            for issue in result.issues:
                typer.echo(f"issue: {issue}")
            raise typer.Exit(code=1)

    _run_cli(_command)


@sync_app.command("status")
def sync_status(
    workspace: str | None = typer.Option(None, "--workspace"),
    registry: str | None = typer.Option(None, "--registry"),
    wiki_id: str | None = typer.Option(None, "--wiki-id"),
) -> None:
    def _command() -> None:
        wiki = _load_wiki(registry, workspace, wiki_id)
        result = SyncService().execute(wiki, _actor(), SyncInput(mode="status"))
        typer.echo(f"mode={result.mode}")
        for changed_file in result.changed_files:
            typer.echo(changed_file)

    _run_cli(_command)


@sync_app.command("pull-view")
def sync_pull_view(
    workspace: str | None = typer.Option(None, "--workspace"),
    registry: str | None = typer.Option(None, "--registry"),
    wiki_id: str | None = typer.Option(None, "--wiki-id"),
) -> None:
    def _command() -> None:
        wiki = _load_wiki(registry, workspace, wiki_id)
        result = SyncService().execute(wiki, _actor(), SyncInput(mode="pull-view"))
        typer.echo(f"mode={result.mode}")
        for changed_file in result.changed_files:
            typer.echo(changed_file)

    _run_cli(_command)


@sync_app.command("push-view")
def sync_push_view(
    doc_ids: list[str] = typer.Option(None, "--doc-id"),
    workspace: str | None = typer.Option(None, "--workspace"),
    registry: str | None = typer.Option(None, "--registry"),
    wiki_id: str | None = typer.Option(None, "--wiki-id"),
) -> None:
    def _command() -> None:
        wiki = _load_wiki(registry, workspace, wiki_id)
        result = SyncService().execute(wiki, _actor(), SyncInput(mode="push-view", doc_ids=doc_ids or None))
        typer.echo(f"mode={result.mode}")
        for changed_file in result.changed_files:
            typer.echo(changed_file)

    _run_cli(_command)


@app.command("feedback")
def feedback(
    query_id: str = typer.Option(..., "--query-id"),
    approved: bool = typer.Option(False, "--approved/--not-approved"),
    missing_evidence: bool = typer.Option(False, "--missing-evidence"),
    rewrite_targets: list[str] = typer.Option(None, "--rewrite-target"),
    notes: str = typer.Option("", "--notes"),
    workspace: str | None = typer.Option(None, "--workspace"),
    registry: str | None = typer.Option(None, "--registry"),
    wiki_id: str | None = typer.Option(None, "--wiki-id"),
) -> None:
    def _command() -> None:
        wiki = _load_wiki(registry, workspace, wiki_id)
        result = FeedbackService().record(
            wiki,
            FeedbackInput(
                query_id=query_id,
                approved=approved,
                missing_evidence=missing_evidence,
                rewrite_targets=rewrite_targets or [],
                notes=notes,
            ),
        )
        typer.echo(f"created_review_item={result.created_review_item}")

    _run_cli(_command)


@app.command("weekly-review")
def weekly_review(
    workspace: str | None = typer.Option(None, "--workspace"),
    registry: str | None = typer.Option(None, "--registry"),
    wiki_id: str | None = typer.Option(None, "--wiki-id"),
) -> None:
    def _command() -> None:
        wiki = _load_wiki(registry, workspace, wiki_id)
        report = WeeklyReviewService().generate(wiki)
        typer.echo(report.summary)
        for action in report.suggested_actions:
            typer.echo(action)

    _run_cli(_command)


@approvals_app.command("propose")
def approvals_propose(
    proposal_id: str = typer.Option(..., "--proposal-id"),
    doc_id: str = typer.Option(..., "--doc-id"),
    page_type: str = typer.Option(..., "--page-type"),
    topic: str = typer.Option(..., "--topic"),
    problem_cluster: str = typer.Option(..., "--problem-cluster"),
    content: str = typer.Option(..., "--content"),
    source_refs: list[str] = typer.Option(None, "--source-ref"),
    registry: str | None = typer.Option(None, "--registry"),
    wiki_id: str | None = typer.Option(None, "--wiki-id"),
    workspace: str | None = typer.Option(None, "--workspace"),
) -> None:
    def _command() -> None:
        wiki = _load_wiki(registry, workspace, wiki_id)
        result = ApprovalService(registry_path=_resolve_registry_path(registry)).propose(
            wiki=wiki,
            actor=_actor(),
            data=ProposalInput(
                proposal_id=proposal_id,
                doc_id=doc_id,
                page_type=page_type,
                topic=topic,
                problem_cluster=problem_cluster,
                content=content,
                source_refs=source_refs or [],
            ),
        )
        typer.echo(f"status={result.status} proposal_id={result.proposal_id}")

    _run_cli(_command)


@approvals_app.command("approve")
def approvals_approve(
    proposal_id: str = typer.Option(..., "--proposal-id"),
    registry: str | None = typer.Option(None, "--registry"),
    wiki_id: str | None = typer.Option(None, "--wiki-id"),
    workspace: str | None = typer.Option(None, "--workspace"),
) -> None:
    def _command() -> None:
        wiki = _load_wiki(registry, workspace, wiki_id)
        result = ApprovalService(registry_path=_resolve_registry_path(registry)).approve(
            wiki=wiki,
            actor=_actor(),
            proposal_id=proposal_id,
        )
        typer.echo(f"status={result.status} doc_id={result.doc_id}")

    _run_cli(_command)


@approvals_app.command("reject")
def approvals_reject(
    proposal_id: str = typer.Option(..., "--proposal-id"),
    registry: str | None = typer.Option(None, "--registry"),
    wiki_id: str | None = typer.Option(None, "--wiki-id"),
) -> None:
    _resolve_registry_path(registry)
    if not wiki_id:
        raise typer.BadParameter("--wiki-id is required")
    if not proposal_id:
        raise typer.BadParameter("--proposal-id is required")
    typer.echo("approval reject is not implemented in Phase 1")
    raise typer.Exit(code=1)


@app.command("migrate")
def migrate(
    slugify_doc_ids: bool = typer.Option(False, "--slugify-doc-ids"),
    normalize_doc_ids: bool = typer.Option(False, "--normalize-doc-ids"),
    workspace: str | None = typer.Option(None, "--workspace"),
    registry: str | None = typer.Option(None, "--registry"),
    wiki_id: str | None = typer.Option(None, "--wiki-id"),
) -> None:
    def _command() -> None:
        if not slugify_doc_ids and not normalize_doc_ids:
            raise ValueError("no migration selected")
        if workspace and registry is None and wiki_id is None:
            wiki_root = Path(workspace)
        else:
            wiki = _load_wiki(registry, workspace, wiki_id)
            wiki_root = Path(wiki.workspace_path)
        if normalize_doc_ids:
            result = NormalizeDocIdsMigration().run(wiki_root)
        else:
            result = SlugifyDocIdsMigration().run(wiki_root)
        typer.echo(f"changed_count={result.changed_count}")
        if result.backup_path:
            typer.echo(f"backup_path={result.backup_path}")

    _run_cli(_command)


@app.command("maintain")
def maintain(
    workspace: str | None = typer.Option(None, "--workspace"),
    registry: str | None = typer.Option(None, "--registry"),
    wiki_id: str | None = typer.Option(None, "--wiki-id"),
) -> None:
    """Run the slow self-evolution loop and print the quality report."""
    def _command() -> None:
        wiki = _load_wiki(registry, workspace, wiki_id)

        summary = MaintenanceService().run(wiki)
        typer.echo("maintenance summary:")
        for key, value in summary.items():
            typer.echo(f"  {key}={value}")

        report = QualityReportService().generate(wiki)
        typer.echo("quality report:")
        for key, value in report.items():
            typer.echo(f"  {key}={value}")

    _run_cli(_command)


def main() -> None:
    timeout_seconds = _cli_timeout_seconds()
    if timeout_seconds > 0:
        signal.signal(signal.SIGALRM, _raise_cli_timeout)
        signal.alarm(timeout_seconds)
    try:
        app()
    except TimeoutError as exc:
        typer.echo(json.dumps(error_payload(exc), ensure_ascii=False, separators=(",", ":")))
        raise typer.Exit(code=1) from exc
    finally:
        if timeout_seconds > 0:
            signal.alarm(0)
