"""Test that `aw-agent serve` cancels the SIGALRM timer to avoid 300s self-kill."""
from unittest.mock import patch

from agent_wiki.transports.cli.app import serve


def test_serve_cancels_sigalrm():
    """serve() must call signal.alarm(0) to cancel the 300s CLI timeout."""
    with patch("agent_wiki.transports.cli.app.signal") as mock_signal, \
         patch("agent_wiki.transports.cli.app.run_stdio_server"):
        mock_signal.alarm.return_value = 0
        try:
            serve(workspace=None, registry=None)
        except SystemExit:
            pass  # typer may exit
        mock_signal.alarm.assert_called_with(0)
