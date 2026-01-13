"""CLI interface for the memory dump debugger."""

from pathlib import Path

import click
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from dump_debugger.workflows import run_analysis

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
    "--interactive/--no-interactive",
    default=True,
    help="Interactive mode - ask follow-up questions (default: enabled)"
)
@click.option(
    "--show-command-output/--no-show-command-output",
    default=True,
    help="Show debugger command outputs (default: enabled)"
)
@click.option(
    "--log-output",
    "-l",
    type=click.Path(path_type=Path),
    help="Save all console output to log file for later analysis"
)
@click.option(
    "--local-only",
    is_flag=True,
    default=False,
    help="🔒 SECURITY: Force local-only mode - no data leaves your machine (requires Ollama)"
)
@click.option(
    "--audit-redaction",
    is_flag=True,
    default=False,
    help="Enable audit logging for data redaction (logs what was redacted before cloud calls)"
)
@click.option(
    "--show-redacted-values",
    is_flag=True,
    default=False,
    help="⚠️  CAUTION: Show actual redacted values in audit log (for debugging). Security risk!"
)

def analyze(
    dump_path: Path,
    issue: str,
    output: Path | None,
    interactive: bool,
    show_command_output: bool,
    log_output: Path | None,
    local_only: bool,
    audit_redaction: bool,
    show_redacted_values: bool
) -> None:
    """Analyze a memory dump file.
    
    Example:
        dump-debugger analyze crash.dmp --issue "Application crashed on startup"
        dump-debugger analyze crash.dmp --issue "App hanging" --log-output analysis.log
        dump-debugger analyze crash.dmp --issue "OOM" --local-only
        dump-debugger analyze crash.dmp --issue "Crash" --audit-redaction
    """
    try:
        # Apply security flags to config
        if local_only:
            from dump_debugger.config import settings
            settings.local_only_mode = True
            console.print("[green]🔒 LOCAL-ONLY MODE enabled - all processing stays on your machine[/green]")
        
        if audit_redaction:
            from dump_debugger.config import settings
            settings.enable_redaction_audit = True
            console.print("[cyan]📋 Redaction audit logging enabled[/cyan]")
        
        if show_redacted_values:
            from dump_debugger.config import settings
            settings.show_redacted_values = True
            console.print("[bold red]⚠️  WARNING: Showing redacted values in audit log (security risk!)[/bold red]")
        
        if interactive:
            console.print("[cyan]Interactive mode enabled - you can ask follow-up questions after analysis[/cyan]")
        

        # Run the hypothesis-driven analysis
        report = run_analysis(
            dump_path, 
            issue, 
            show_command_output=show_command_output,
            log_to_file=(log_output is not None),
            log_output_path=log_output,
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


@cli.command()
@click.argument("sample_file", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--pattern-name",
    "-p",
    help="Test only a specific pattern by name"
)
def test_patterns(sample_file: Path, pattern_name: str | None) -> None:
    """Test redaction patterns on a sample file.
    
    This command helps you validate custom redaction patterns before using them
    in production. It shows what would be redacted and provides statistics.
    
    Example:
        dump-debugger test-patterns sample.txt
        dump-debugger test-patterns sample.txt --pattern-name CustomSSN
    """
    from rich.syntax import Syntax
    from rich.table import Table
    from dump_debugger.security.redactor import DataRedactor, load_custom_patterns, RedactionPattern
    from dump_debugger.config import settings
    
    try:
        # Read sample file
        sample_text = sample_file.read_text(encoding='utf-8')
        console.print(f"\n[cyan]Testing patterns on:[/cyan] {sample_file}")
        console.print(f"[dim]File size: {len(sample_text):,} characters[/dim]\n")
        
        # Load patterns
        custom_patterns = load_custom_patterns(settings.redaction_patterns_path)
        
        # Create redactor (without audit logging for testing)
        redactor = DataRedactor(
            custom_patterns=custom_patterns,
            enable_audit=False,
            redaction_placeholder="[REDACTED]"
        )
        
        # Filter to specific pattern if requested
        if pattern_name:
            redactor.patterns = [p for p in redactor.patterns if p.name == pattern_name]
            if not redactor.patterns:
                console.print(f"[red]✗ Pattern '{pattern_name}' not found[/red]")
                console.print(f"\n[yellow]Available patterns:[/yellow]")
                all_redactor = DataRedactor(custom_patterns=custom_patterns, enable_audit=False)
                for p in all_redactor.patterns:
                    console.print(f"  • {p.name}")
                raise click.Abort()
            console.print(f"[green]Testing pattern:[/green] {pattern_name}\n")
        
        # Apply redaction
        redacted_text, total_redactions = redactor.redact_text(sample_text, context="test")
        
        # Show results
        if total_redactions == 0:
            console.print("[yellow]No sensitive data detected in sample file[/yellow]")
            console.print("[dim]This could mean:[/dim]")
            console.print("[dim]  • Sample doesn't contain sensitive data[/dim]")
            console.print("[dim]  • Patterns need adjustment[/dim]")
            console.print("[dim]  • Use a more representative sample[/dim]")
        else:
            console.print(f"[green]✓ Found and redacted {total_redactions} sensitive patterns[/green]\n")
            
            # Count matches per pattern
            pattern_stats = []
            for pattern in redactor.patterns:
                matches = list(pattern.compiled.finditer(sample_text))
                if matches:
                    pattern_stats.append({
                        "name": pattern.name,
                        "count": len(matches),
                        "severity": pattern.severity,
                        "description": pattern.description
                    })
            
            # Show statistics table
            if pattern_stats:
                table = Table(title="Redaction Statistics")
                table.add_column("Pattern", style="cyan")
                table.add_column("Matches", justify="right", style="yellow")
                table.add_column("Severity", style="red")
                table.add_column("Description", style="dim")
                
                for stat in sorted(pattern_stats, key=lambda x: x["count"], reverse=True):
                    severity_color = {
                        "critical": "[bold red]CRITICAL[/bold red]",
                        "warning": "[yellow]WARNING[/yellow]",
                        "info": "[blue]INFO[/blue]"
                    }.get(stat["severity"], stat["severity"])
                    
                    table.add_row(
                        stat["name"],
                        str(stat["count"]),
                        severity_color,
                        stat["description"][:50] + "..." if len(stat["description"]) > 50 else stat["description"]
                    )
                
                console.print(table)
                console.print()
            
            # Show before/after comparison (truncated)
            console.print(Panel(
                "[bold]Before (Original):[/bold]",
                border_style="red"
            ))
            
            # Show first 500 chars of original
            preview_len = min(500, len(sample_text))
            console.print(Syntax(sample_text[:preview_len], "text", theme="monokai", line_numbers=True))
            if len(sample_text) > preview_len:
                console.print(f"[dim]... ({len(sample_text) - preview_len:,} more characters)[/dim]")
            console.print()
            
            console.print(Panel(
                "[bold]After (Redacted):[/bold]",
                border_style="green"
            ))
            
            # Show first 500 chars of redacted
            preview_len = min(500, len(redacted_text))
            console.print(Syntax(redacted_text[:preview_len], "text", theme="monokai", line_numbers=True))
            if len(redacted_text) > preview_len:
                console.print(f"[dim]... ({len(redacted_text) - preview_len:,} more characters)[/dim]")
            console.print()
            
            # Calculate coverage
            original_size = len(sample_text)
            redacted_size = len(redacted_text)
            redaction_bytes = original_size - redacted_size + (total_redactions * len("[REDACTED]"))
            coverage_pct = (redaction_bytes / original_size * 100) if original_size > 0 else 0
            
            console.print(f"[cyan]Coverage:[/cyan] {coverage_pct:.2f}% of content affected by redaction")
            console.print(f"[cyan]Original size:[/cyan] {original_size:,} chars")
            console.print(f"[cyan]Redacted size:[/cyan] {redacted_size:,} chars")
        
        # Show validation warnings
        console.print(f"\n[cyan]Pattern Validation:[/cyan]")
        console.print(f"[green]✓[/green] All {len(redactor.patterns)} patterns compiled successfully")
        console.print(f"[dim]Run this command regularly to test your custom patterns[/dim]")
        
    except Exception as e:
        console.print(f"[red]Error testing patterns: {e}[/red]")
        import traceback
        console.print(f"[dim]{traceback.format_exc()}[/dim]")
        raise click.Abort()


def main() -> None:
    """Entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()
