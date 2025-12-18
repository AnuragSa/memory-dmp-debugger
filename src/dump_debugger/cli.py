"""CLI interface for the memory dump debugger."""

from pathlib import Path

import click
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from dump_debugger.workflows import run_analysis, enable_logging

console = Console()


@click.group()
@click.version_option()
def cli() -> None:
    """Memory Dump Debugger - AI-powered crash dump analysis."""
    pass


@cli.command()
@click.argument("dump_path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--issue",
    "-i",
    required=True,
    help="Description of the issue to investigate (e.g., 'Application crashed on startup')"
)
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    help="Save report to file (default: print to console)"
)
@click.option(
    "--interactive",
    is_flag=True,
    help="Interactive mode - pause after each step for user confirmation"
)
@click.option(
    "--show-commands",
    is_flag=True,
    default=False,
    help="Show debugger command outputs (default: hidden)"
)
@click.option(
    "--log-output",
    "-l",
    type=click.Path(path_type=Path),
    help="Save all console output to log file for later analysis"
)
def analyze(
    dump_path: Path,
    issue: str,
    output: Path | None,
    interactive: bool,
    show_commands: bool,
    log_output: Path | None
) -> None:
    """Analyze a memory dump file.
    
    Example:
        dump-debugger analyze crash.dmp --issue "Application crashed on startup"
        dump-debugger analyze crash.dmp --issue "App hanging" --log-output analysis.log
    """
    try:
        # Setup console logging if requested
        if log_output:
            enable_logging(log_output)
        
        if interactive:
            console.print("[cyan]Interactive mode enabled - you can ask follow-up questions after analysis[/cyan]")
        
        # Run the hypothesis-driven analysis
        report = run_analysis(
            dump_path, 
            issue, 
            show_commands=show_commands,
            log_to_file=(log_output is not None),
            interactive=interactive
        )
        
        # Save to file if requested
        if output:
            output.write_text(report, encoding="utf-8")
            console.print(f"\n[green]✓[/green] Report saved to: {output}")
        
    except FileNotFoundError as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise click.Abort()
    except ValueError as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise click.Abort()
    except Exception as e:
        console.print(f"[red]Unexpected error: {str(e)}[/red]")
        if console.is_terminal:
            import traceback
            console.print("\n[dim]" + traceback.format_exc() + "[/dim]")
        raise click.Abort()


@cli.command()
@click.argument("dump_path", type=click.Path(exists=True, path_type=Path))
def validate(dump_path: Path) -> None:
    """Validate a dump file and show basic information.
    
    Example:
        dump-debugger validate crash.dmp
    """
    from dump_debugger.core import DebuggerWrapper
    
    try:
        console.print(f"[cyan]Validating:[/cyan] {dump_path}")
        
        debugger = DebuggerWrapper(dump_path)
        dump_info = debugger.validate_dump()
        
        if dump_info["valid"]:
            console.print("[green]✓ Valid dump file[/green]")
            dump_type = debugger.get_dump_type()
            console.print(f"[cyan]Type:[/cyan] {dump_type}-mode")
            
            if dump_info.get("info"):
                console.print("\n[bold]Dump Information:[/bold]")
                console.print(dump_info["info"])
        else:
            console.print(f"[red]✗ Invalid dump file[/red]")
            console.print(f"[red]Error: {dump_info['error']}[/red]")
            raise click.Abort()
            
    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise click.Abort()


@cli.command()
def setup() -> None:
    """Interactive setup wizard to configure the debugger.
    
    Example:
        dump-debugger setup
    """
    from pathlib import Path
    
    console.print("[bold cyan]Memory Dump Debugger Setup[/bold cyan]\n")
    
    env_file = Path(".env")
    env_example = Path(".env.example")
    
    if env_file.exists():
        if not click.confirm("WARNING: .env file already exists. Overwrite?"):
            console.print("[yellow]Setup cancelled[/yellow]")
            return
    
    # Copy example file
    if env_example.exists():
        import shutil
        shutil.copy(env_example, env_file)
        console.print("[green]✓[/green] Created .env file from template")
    else:
        env_file.write_text("")
        console.print("[green]✓[/green] Created empty .env file")
    
    console.print("\n[yellow]Please edit .env file and configure:[/yellow]")
    console.print("  1. Your LLM API key (OpenAI, Anthropic, or Azure)")
    console.print("  2. Path to WinDbg/CDB debugger")
    console.print("  3. Symbol server path")
    console.print(f"\n[cyan]File location:[/cyan] {env_file.absolute()}")


@cli.command()
@click.option(
    "--days",
    "-d",
    type=int,
    default=7,
    help="Delete sessions older than this many days (default: 7)"
)
@click.option(
    "--keep",
    "-k",
    type=int,
    default=5,
    help="Always keep this many most recent sessions (default: 5)"
)
def cleanup(days: int, keep: int) -> None:
    """Clean up old analysis sessions.
    
    Example:
        dump-debugger cleanup --days 7 --keep 5
    """
    from dump_debugger.session import SessionManager
    from dump_debugger.config import settings
    from pathlib import Path
    
    try:
        session_manager = SessionManager(base_dir=Path(settings.sessions_base_dir))
        
        console.print(f"[cyan]Cleaning up sessions older than {days} days (keeping {keep} most recent)...[/cyan]")
        
        deleted = session_manager.cleanup_old_sessions(days_old=days, keep_recent=keep)
        
        if deleted:
            console.print(f"\n[green]✓ Deleted {len(deleted)} session(s):[/green]")
            for session_id in deleted:
                console.print(f"  - {session_id}")
        else:
            console.print("\n[green]✓ No sessions to clean up[/green]")
            
    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise click.Abort()


@cli.command()
@click.option(
    "--limit",
    "-l",
    type=int,
    default=20,
    help="Maximum number of sessions to list (default: 20)"
)
def sessions(limit: int) -> None:
    """List all analysis sessions.
    
    Example:
        dump-debugger sessions
        dump-debugger sessions --limit 10
    """
    from dump_debugger.session import SessionManager
    from dump_debugger.config import settings
    from pathlib import Path
    from rich.table import Table
    
    try:
        session_manager = SessionManager(base_dir=Path(settings.sessions_base_dir))
        
        session_list = session_manager.list_sessions(limit=limit)
        
        if not session_list:
            console.print("[yellow]No sessions found[/yellow]")
            return
        
        # Create table
        table = Table(title=f"Analysis Sessions (showing {len(session_list)} of {limit} max)")
        table.add_column("Session ID", style="cyan", no_wrap=True)
        table.add_column("Dump File", style="green")
        table.add_column("Created", style="blue")
        table.add_column("Last Access", style="blue")
        table.add_column("Size", justify="right", style="yellow")
        table.add_column("Evidence", justify="right", style="magenta")
        
        for session in session_list:
            from datetime import datetime
            
            # Parse timestamps
            created = session.get('created_at', '')
            last_accessed = session.get('last_accessed', '')
            
            try:
                created_dt = datetime.fromisoformat(created)
                created_str = created_dt.strftime("%Y-%m-%d %H:%M")
            except:
                created_str = created[:16]
            
            try:
                accessed_dt = datetime.fromisoformat(last_accessed)
                accessed_str = accessed_dt.strftime("%Y-%m-%d %H:%M")
            except:
                accessed_str = last_accessed[:16]
            
            table.add_row(
                session['session_id'],
                session.get('dump_name', 'N/A'),
                created_str,
                accessed_str,
                f"{session.get('size_mb', 0):.2f} MB",
                str(session.get('evidence_count', 0))
            )
        
        console.print(table)
        console.print(f"\n[dim]Base directory: {session_manager.base_dir}[/dim]")
        
    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise click.Abort()


def main() -> None:
    """Entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()
