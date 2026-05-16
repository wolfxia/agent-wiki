from pathlib import Path

import typer

from agent_wiki.application.capture_raw import CaptureRawService
from agent_wiki.application.compile_update import CompileUpdateService
from agent_wiki.application.linting import LintService
from agent_wiki.application.query import QueryService
from agent_wiki.bootstrap.container import Container
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor
from agent_wiki.domain.models import CaptureRawInput, CompileUpdateInput, QueryInput

app = typer.Typer(help="Agent Wiki CLI")


def _load_wiki(workspace: str | None):
    registry = RegistryLoader().load(Path("tests/fixtures/registry.yaml"))
    wiki = registry.wikis[0]
    if workspace:
        wiki = wiki.model_copy(update={"workspace_path": workspace})
    return wiki


def _actor() -> ResolvedActor:
    return ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")


@app.callback()
def main_callback() -> None:
    """Agent Wiki CLI root."""


@app.command("info")
def info() -> None:
    container = Container()
    typer.echo(f"agent-wiki ready: {container.__class__.__name__}")


@app.command("serve")
def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Start the long-running agent-wiki service."""
    typer.echo(f"agent-wiki serve scaffolded on {host}:{port}")


@app.command("query")
def query(
    text: str = typer.Argument(..., help="Query text"),
    workspace: str | None = typer.Option(None, "--workspace"),
) -> None:
    wiki = _load_wiki(workspace)
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
) -> None:
    wiki = _load_wiki(workspace)
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
) -> None:
    wiki = _load_wiki(workspace)
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
def lint(workspace: str | None = typer.Option(None, "--workspace")) -> None:
    wiki = _load_wiki(workspace)
    result = LintService().run(wiki)
    if result.ok:
        typer.echo("ok: no issues")
    else:
        for issue in result.issues:
            typer.echo(f"issue: {issue}")
        raise typer.Exit(code=1)


def main() -> None:
    app()
