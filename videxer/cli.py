from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
import click

from .indexer import write_index_files
from .utils import ensure_dir


def resolve_output_dir(output_dir: Optional[str], input_dir: Path) -> Path:
    """Resolve output directory, defaulting to input directory."""
    if output_dir:
        return Path(output_dir)
    return input_dir


@click.command()
@click.argument("input_dir", type=click.Path(file_okay=False, dir_okay=True, path_type=Path), default=Path("."))
@click.option("--output-dir", type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
              help="Output directory for index files (defaults to input directory)")
@click.option("--html-path", type=click.Path(dir_okay=False, path_type=Path),
              help="Custom path for index.html file")
@click.option("--json-path", type=click.Path(dir_okay=False, path_type=Path),
              help="Custom path for index.json file")
def cli(input_dir: Path, output_dir: Optional[Path], html_path: Optional[Path], json_path: Optional[Path]):
    """Generate a static index.html and index.json for the given media directory.

    Scans the input directory for media files (videos, audio, images) and creates
    a browsable HTML interface. Supports both generic media libraries and
    Vimeo download directories (backwards compatible).
    """
    input_dir = Path(input_dir).resolve()

    if not input_dir.exists() or not input_dir.is_dir():
        raise click.ClickException(f"Input directory not found: {input_dir}")

    # Resolve output directory
    if output_dir:
        output_dir = Path(output_dir).resolve()
        ensure_dir(output_dir)
    else:
        output_dir = input_dir

    # Resolve custom paths relative to output directory
    if html_path:
        html_path = Path(html_path)
        if not html_path.is_absolute():
            html_path = output_dir / html_path
    if json_path:
        json_path = Path(json_path)
        if not json_path.is_absolute():
            json_path = output_dir / json_path

    click.echo(f"Scanning media directory: {input_dir}")
    write_index_files(input_dir, html_path, json_path)

    html_file = html_path or (output_dir / "index.html")
    json_file = json_path or (output_dir / "index.json")

    click.echo(f"Generated files:")
    click.echo(f"  HTML: {html_file}")
    click.echo(f"  JSON: {json_file}")
    click.echo(f"\nOpen {html_file} in your browser to view the media library.")
