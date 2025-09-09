from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
import click

from .indexer import write_index_files
from .utils import ensure_dir, detect_media_structure, MediaStructure, load_config, save_config, merge_config_with_args


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
@click.option("--generate-thumbnails", is_flag=True, default=False,
              help="Generate thumbnails for video files")
@click.option("--generate-motion-thumbnails", is_flag=True, default=False,
              help="Generate animated motion thumbnails for video files")
@click.option("--generate-transcodes", is_flag=True, default=False,
              help="Generate web-optimized transcoded versions of videos")
@click.pass_context
def cli(ctx, input_dir: Path, output_dir: Optional[Path], html_path: Optional[Path], json_path: Optional[Path], generate_thumbnails: bool, generate_motion_thumbnails: bool, generate_transcodes: bool):
    """Generate a static index.html and index.json for the given media directory.

    Scans the input directory for media files (videos, audio, images) and creates
    a browsable HTML interface. Supports both generic media libraries and
    Vimeo download directories (backwards compatible).
    """
    input_dir = Path(input_dir).resolve()

    if not input_dir.exists() or not input_dir.is_dir():
        raise click.ClickException(f"Input directory not found: {input_dir}")

    # Load existing config
    config = load_config(input_dir)

    # Determine which arguments were actually provided by the user
    provided_args = {}

    # Check if options were provided (not just defaults)
    if ctx.params.get('output_dir') is not None:
        provided_args['output_dir'] = str(output_dir)
    if ctx.params.get('html_path') is not None:
        provided_args['html_path'] = str(html_path)
    if ctx.params.get('json_path') is not None:
        provided_args['json_path'] = str(json_path)
    if generate_thumbnails:
        provided_args['generate_thumbnails'] = generate_thumbnails
    if generate_motion_thumbnails:
        provided_args['generate_motion_thumbnails'] = generate_motion_thumbnails
    if generate_transcodes:
        provided_args['generate_transcodes'] = generate_transcodes

    # Merge config with provided args (CLI takes precedence)
    merged_config = merge_config_with_args(config, provided_args)

    # Use merged values
    output_dir = merged_config.get('output_dir')
    html_path = merged_config.get('html_path')
    json_path = merged_config.get('json_path')
    generate_thumbnails = merged_config.get('generate_thumbnails', False)
    generate_motion_thumbnails = merged_config.get('generate_motion_thumbnails', False)
    generate_transcodes = merged_config.get('generate_transcodes', False)

    # Convert string paths back to Path objects
    if output_dir:
        output_dir = Path(output_dir).resolve()
        ensure_dir(output_dir)
    else:
        output_dir = input_dir

    if html_path:
        html_path = Path(html_path)
        if not html_path.is_absolute():
            html_path = output_dir / html_path
    if json_path:
        json_path = Path(json_path)
        if not json_path.is_absolute():
            json_path = output_dir / json_path

    click.echo(f"Scanning media directory: {input_dir}")
    structure = detect_media_structure(input_dir)
    click.echo(f"Detected structure: {structure.value}")

    write_index_files(input_dir, html_path, json_path, generate_thumbnails, generate_motion_thumbnails, generate_transcodes)

    html_file = html_path or (output_dir / "index.html")
    json_file = json_path or (output_dir / "index.json")

    click.echo(f"Generated files:")
    click.echo(f"  HTML: {html_file}")
    click.echo(f"  JSON: {json_file}")
    click.echo(f"\nOpen {html_file} in your browser to view the media library.")

    # Save current configuration for future runs
    save_config(input_dir, merged_config)
