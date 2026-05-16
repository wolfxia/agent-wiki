import typer

from agent_wiki.bootstrap.container import Container

app = typer.Typer(help="Agent Wiki CLI")


@app.callback()
def main_callback() -> None:
    """Agent Wiki CLI root."""


@app.command("info")
def info() -> None:
    container = Container()
    typer.echo(f"agent-wiki ready: {container.__class__.__name__}")


def main() -> None:
    app()
