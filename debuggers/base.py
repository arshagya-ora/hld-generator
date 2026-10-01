"""
Base Framework for Agent Debuggers.
Provides common CLI arguments, logging setup, and base class for agent debuggers.
"""

import argparse
import asyncio
import json
import logging
import sys
from typing import Any, Dict, Optional
from abc import ABC, abstractmethod
from pathlib import Path

def _load_debugger_env() -> None:
    """Best-effort .env loading for debugger scripts."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return

    project_dir = Path(__file__).resolve().parent.parent
    candidates = [
        Path.cwd() / ".env",
        project_dir / ".env",
        project_dir.parent / ".env",
    ]

    for env_path in candidates:
        if env_path.exists():
            load_dotenv(env_path, override=False)

# Configure Rich logging if available
try:
    from rich.console import Console
    from rich.logging import RichHandler
    from rich.theme import Theme
    
    custom_theme = Theme({
        "info": "dim cyan",
        "warning": "magenta",
        "error": "bold red",
        "success": "green"
    })
    console = Console(theme=custom_theme)
    HAS_RICH = True
except ImportError:
    HAS_RICH = False
    console = None

def setup_logger(name: str, debug: bool = False) -> logging.Logger:
    """Setup a formatted logger for the debugger."""
    level = logging.DEBUG if debug else logging.INFO
    
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # Remove existing handlers
    logger.handlers = []
    
    if HAS_RICH:
        handler = RichHandler(console=console, show_path=False, markup=True)
        handler.setFormatter(logging.Formatter("%(message)s"))
    else:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%H:%M:%S'
        ))
    
    logger.addHandler(handler)
    return logger

class AgentDebugger(ABC):
    """
    Abstract Base Class for Agent Debuggers.
    """
    
    def __init__(self, description: str):
        self.parser = argparse.ArgumentParser(description=description)
        self.parser.add_argument("--debug", action="store_true", help="Enable debug logging")
        self.parser.add_argument("--output", type=str, help="Path to save output JSON")
        self.parser.add_argument("--mock-input", type=str, help="Path to mock input JSON file")
        
        self.add_arguments(self.parser)
        
    def add_arguments(self, parser: argparse.ArgumentParser):
        """Override to add agent-specific arguments."""
        pass
        
    @abstractmethod
    async def execute(self, args: argparse.Namespace, logger: logging.Logger) -> Dict[str, Any]:
        """Implement specific agent execution logic here."""
        pass
        
    def run(self):
        """Main entry point."""
        _load_debugger_env()
        args = self.parser.parse_args()
        self.logger = setup_logger(self.__class__.__name__, args.debug)
        
        self.logger.info(f"[bold green]Starting {self.__class__.__name__}...[/]")
        
        try:
            # Run async execution
            result = asyncio.run(self.execute(args, self.logger))
            
            # Output handling
            if args.output:
                output_path = Path(args.output).resolve()
                
                # If the path is a directory, append a default filename
                if output_path.is_dir():
                    default_name = f"{self.__module__.split('.')[-1]}_output.json".lower()
                    output_path = output_path / default_name
                elif not output_path.suffix:
                    # If it has no extension, treat it as a directory to be safe
                    output_path.mkdir(parents=True, exist_ok=True)
                    default_name = f"{self.__module__.split('.')[-1]}_output.json".lower()
                    output_path = output_path / default_name
                
                # Ensure parent directories exist
                output_path.parent.mkdir(parents=True, exist_ok=True)
                
                with open(output_path, 'w', encoding='utf-8') as f:
                    json.dump(result, f, indent=2, default=str)
                self.logger.info(f"[success]Output saved to {output_path}[/]")
            else:
                self.logger.info("\n[bold]Execution Result:[/]")
                # Print truncated result to console if no file output
                json_str = json.dumps(result, indent=2, default=str)
                if len(json_str) > 2000 and not args.debug:
                    self.logger.info(json_str[:2000] + "\n... (truncated)")
                else:
                    self.logger.info(json_str)
                    
        except Exception as e:
            self.logger.error(f"[error]Execution failed: {str(e)}[/]")
            if args.debug:
                import traceback
                traceback.print_exc()
            sys.exit(1)

def load_json_input(path: str) -> Dict[str, Any]:
    """Helper to load JSON input from file."""
    if not path:
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading input file {path}: {e}")
        sys.exit(1)
