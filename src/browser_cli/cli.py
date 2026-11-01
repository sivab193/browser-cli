"""browser-cli command line interface.

Designed so that any coding agent or LLM can shell out to it:

    browser-cli run --url https://example.com --goal "find the pricing page" --json

With --json, every step and the final result are emitted as JSON lines (NDJSON),
which is trivial for another program to parse. Without it, a human-readable live
view is rendered. Exit code is 0 on success (goal done), 1 on blocked, 2 on
failure/error — so callers can branch on the result without parsing output.
"""

from __future__ import annotations

import json

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .agent import Agent
from .bivia import BiviaClient, BiviaError
from .bootstrap import browsers_path, install_chromium
from .browser import Browser
from .text_helper import TextHelper

app = typer.Typer(
    add_completion=False,
    help="A fast web-browsing agent driven by the Bivia decision model.",
    no_args_is_help=True,
)
console = Console()

EXIT_DONE = 0
EXIT_BLOCKED = 1
EXIT_FAILED = 2


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"browser-cli {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    version: bool = typer.Option(
        False, "--version", "-V", callback=_version_callback, is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    pass


@app.command()
def run(
    goal: str = typer.Option(..., "--goal", "-g", help="Natural-language goal for the agent."),
    url: str = typer.Option(..., "--url", "-u", help="Starting URL."),
    json_out: bool = typer.Option(
        False, "--json", help="Emit NDJSON (one JSON object per step + final result)."
    ),
    headless: bool = typer.Option(
        False, "--headless/--headed", help="Run the browser without a visible window."
    ),
    max_steps: int = typer.Option(25, "--max-steps", help="Maximum decision steps."),
    mode: str = typer.Option("fast", "--mode", help="Bivia mode: fast or deep."),
    profile: str = typer.Option(
        None, "--profile", help="Path to a persistent browser profile dir (reuses logins)."
    ),
    api_key: str = typer.Option(
        None, "--api-key", envvar="A8_API_KEY", help="Bivia API key (or set A8_API_KEY)."
    ),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress the live step view."),
) -> None:
    """Drive a browser toward GOAL starting at URL."""
    try:
        bivia = BiviaClient(api_key=api_key, mode=mode)
    except BiviaError as exc:
        _emit_error(str(exc), json_out)
        raise typer.Exit(EXIT_FAILED)

    browser = Browser(headless=headless, user_data_dir=profile)
    text_helper = TextHelper()

    if not json_out and not quiet:
        console.print(f"[bold cyan]browser-cli[/] goal: {goal}")
        console.print(f"[dim]start:[/] {url}  [dim]mode:[/] {mode}  "
                      f"[dim]text model:[/] {'on' if text_helper.enabled else 'off (heuristic)'}")

    final_status = "failed"
    final_state = None
    agent = Agent(
        url=url, goal=goal, bivia=bivia, browser=browser, text_helper=text_helper,
        max_steps=max_steps, mode=mode,
    )
    try:
        with agent:
            for state in agent.run():
                final_state = state
                final_status = state.status
                if json_out:
                    print(json.dumps(state.to_dict()), flush=True)
                elif not quiet:
                    _print_step(state)
    except BiviaError as exc:
        _emit_error(f"Bivia error: {exc}", json_out)
        raise typer.Exit(EXIT_FAILED)
    except Exception as exc:  # pragma: no cover - surface unexpected failures cleanly
        _emit_error(f"Unexpected error: {exc}", json_out)
        raise typer.Exit(EXIT_FAILED)

    if json_out:
        print(json.dumps({
            "result": final_status,
            "goal": goal,
            "url": final_state.url if final_state else url,
            "steps": final_state.step if final_state else 0,
            "elapsed_ms": final_state.elapsed_ms if final_state else 0,
            "note": final_state.note if final_state else "",
        }), flush=True)
    elif not quiet:
        _print_summary(final_status, final_state)

    if final_status == "done":
        raise typer.Exit(EXIT_DONE)
    if final_status == "blocked":
        raise typer.Exit(EXIT_BLOCKED)
    raise typer.Exit(EXIT_FAILED)


@app.command()
def install(
    with_deps: bool = typer.Option(
        False, "--with-deps", help="Also install OS-level dependencies (Linux; needs root)."
    ),
) -> None:
    """Download the Chromium browser that the agent drives.

    Optional — `run` and `doctor` auto-install Chromium on first use. Run this to
    pre-warm the browser (useful before offline or `uvx` invocations)."""
    console.print(f"[dim]browsers path:[/] {browsers_path()}")
    console.print("Installing Chromium …")
    if install_chromium(with_deps=with_deps):
        console.print("[green]OK[/] Chromium installed.")
        raise typer.Exit(0)
    console.print("[red]FAIL[/] Could not install Chromium.")
    raise typer.Exit(EXIT_FAILED)


@app.command()
def doctor() -> None:
    """Check that Bivia credentials and Playwright browsers are ready."""
    ok = True

    # Bivia key
    try:
        BiviaClient()
        console.print("[green]OK[/] Bivia API key found (A8_API_KEY).")
    except BiviaError as exc:
        ok = False
        console.print(f"[red]FAIL[/] {exc}")

    # Text model (optional)
    th = TextHelper()
    if th.enabled:
        console.print(f"[green]OK[/] Text model configured ({th.model}).")
    else:
        console.print("[yellow]INFO[/] No text model (TEXT_MODEL_API_KEY). "
                      "TYPE_TEXT falls back to a heuristic.")

    # Playwright browser — auto-installs Chromium on first run.
    console.print(f"[dim]browsers path:[/] {browsers_path()}")
    try:
        b = Browser(headless=True, auto_install=True)
        b.start()
        b.close()
        console.print("[green]OK[/] Playwright Chromium launches.")
    except Exception as exc:  # surface unexpected failures cleanly
        ok = False
        console.print(f"[red]FAIL[/] Playwright: {exc}")
        console.print("[dim]Try: browser-cli install[/]")

    raise typer.Exit(0 if ok else EXIT_FAILED)


# --- rendering --------------------------------------------------------------

def _print_step(state) -> None:
    color = {"running": "white", "done": "green", "blocked": "yellow", "failed": "red"}.get(
        state.status, "white"
    )
    tgt = f" → [{state.target_index}] {state.target_name}" if state.target_index else ""
    txt = f'  "{state.text}"' if state.text else ""
    console.print(
        f"[dim]{state.elapsed_ms:>6}ms[/] [bold]{state.step:>2}[/] "
        f"[{color}]{state.operation or '-':<11}[/]{tgt}{txt}"
        + (f"  [dim]{state.note}[/]" if state.note else "")
    )


def _print_summary(status, state) -> None:
    color = {"done": "green", "blocked": "yellow", "failed": "red"}.get(status, "white")
    table = Table(show_header=False, box=None)
    table.add_row("result", f"[{color}]{status}[/]")
    if state:
        table.add_row("steps", str(state.step))
        table.add_row("elapsed", f"{state.elapsed_ms} ms")
        table.add_row("url", state.url)
        if state.note:
            table.add_row("note", state.note)
    console.print(table)


def _emit_error(msg: str, json_out: bool) -> None:
    if json_out:
        print(json.dumps({"result": "error", "error": msg}), flush=True)
    else:
        console.print(f"[red]error:[/] {msg}", highlight=False)


if __name__ == "__main__":
    app()
