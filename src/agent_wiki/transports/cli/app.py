from pathlib import Path
import os

import typer

from agent_wiki.application.capture_raw import CaptureRawService
from agent_wiki.application.compile_update import CompileUpdateService
from agent_wiki.application.linting import LintService
from agent_wiki.application.maintenance import MaintenanceService
from agent_wiki.application.quality_report import QualityReportService
from agent_wiki.application.query import QueryService
from agent_wiki.bootstrap.container import Container
from agent_wiki.bootstrap.registry_loader import RegistryLoader, WikiConfig
from agent_wiki.domain.contracts import ResolvedActor
from agent_wiki.domain.models import CaptureRawInput, CompileUpdateInput, IdentityContext, QueryInput
from agent_wiki.infrastructure.identity.resolver import IdentityResolver
from agent_wiki.settings import DEFAULT_REGISTRY_PATH
from agent_wiki.transports.mcp.server import run_stdio_server

app = typer.Typer(help="Agent Wiki CLI")


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


@app.command("serve")
def serve(
    workspace: str | None = typer.Option(None, "--workspace"),
    registry: str | None = typer.Option(None, "--registry"),
) -> None:
    """Start the long-running agent-wiki MCP stdio service."""
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
    wiki = _load_wiki(registry, workspace, wiki_id)
    result = QueryService().execute(wiki=wiki, actor=_actor(), data=QueryInput(query=text))
    typer.echo(f"hit_count={result.hit_count}")
    typer.echo(f"l1_answer={result.l1_answer}")
    for hit in result.hits:
        typer.echo(f"  hit: {hit.doc_id} score={hit.score}")


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
    wiki = _load_wiki(registry, workspace, wiki_id)
    result = CaptureRawService().execute(
        wiki=wiki, actor=_actor(),
        data=CaptureRawInput(
            doc_id=doc_id, topic=topic, problem_cluster=problem_cluster,
            content=content, source_refs=[],
        ),
    )
    typer.echo(f"status={result.status} doc_id={result.doc_id}")


@app.command("compile-update")
def compile_update(
    doc_id: str = typer.Argument(...),
    page_type: str = typer.Option(...),
    topic: str = typer.Option(...),
    problem_cluster: str = typer.Option(...),
    content: str = typer.Option(...),
    source_refs: str = typer.Option("", help="Comma-separated source_refs"),
    workspace: str | None = typer.Option(None, "--workspace"),
    registry: str | None = typer.Option(None, "--registry"),
    wiki_id: str | None = typer.Option(None, "--wiki-id"),
) -> None:
    wiki = _load_wiki(registry, workspace, wiki_id)
    refs = [r.strip() for r in source_refs.split(",") if r.strip()]
    result = CompileUpdateService().apply(
        wiki=wiki, actor=_actor(),
        data=CompileUpdateInput(
            doc_id=doc_id, page_type=page_type, topic=topic,
            problem_cluster=problem_cluster, content=content, source_refs=refs,
        ),
    )
    typer.echo(f"status={result.status} doc_id={result.doc_id}")


@app.command("lint")
def lint(
    workspace: str | None = typer.Option(None, "--workspace"),
    registry: str | None = typer.Option(None, "--registry"),
    wiki_id: str | None = typer.Option(None, "--wiki-id"),
) -> None:
    wiki = _load_wiki(registry, workspace, wiki_id)
    result = LintService().run(wiki)
    if result.ok:
        typer.echo("ok: no issues")
    else:
        for issue in result.issues:
            typer.echo(f"issue: {issue}")
        raise typer.Exit(code=1)


@app.command("maintain")
def maintain(
    workspace: str | None = typer.Option(None, "--workspace"),
    registry: str | None = typer.Option(None, "--registry"),
    wiki_id: str | None = typer.Option(None, "--wiki-id"),
) -> None:
    """Run the slow self-evolution loop and print the quality report."""
    wiki = _load_wiki(registry, workspace, wiki_id)

    summary = MaintenanceService().run(wiki)
    typer.echo("maintenance summary:")
    for key, value in summary.items():
        typer.echo(f"  {key}={value}")

    report = QualityReportService().generate(wiki)
    typer.echo("quality report:")
    for key, value in report.items():
        typer.echo(f"  {key}={value}")


def main() -> None:
    app()
