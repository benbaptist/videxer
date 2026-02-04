from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
import click
from importlib.metadata import version

from .indexer import write_index_files
from .utils import ensure_dir, detect_media_structure, MediaStructure, load_config, save_config, merge_config_with_args, setup_logging, get_logger, _get_hardware_accelerator


def resolve_output_dir(output_dir: Optional[str], input_dir: Path) -> Path:
    """Resolve output directory, defaulting to input directory."""
    if output_dir:
        return Path(output_dir)
    return input_dir


@click.command()
@click.argument("input_dir", type=click.Path(file_okay=False, dir_okay=True, path_type=Path), default=Path("."))
@click.option("-v", "--version", "show_version", is_flag=True, help="Show version and exit")
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
@click.option("--log-level", type=click.Choice(["CRITICAL","ERROR","WARNING","INFO","DEBUG"], case_sensitive=False), default="INFO",
              help="Log level for console output; file always logs at DEBUG")
@click.pass_context
def cli(ctx, input_dir: Path, show_version: bool, output_dir: Optional[Path], html_path: Optional[Path], json_path: Optional[Path], generate_thumbnails: bool, generate_motion_thumbnails: bool, generate_transcodes: bool, log_level: str):
    """Generate a static index.html and index.json for the given media directory.

    Scans the input directory for media files (videos, audio, images) and creates
    a browsable HTML interface. Supports both generic media libraries and
    Vimeo download directories (backwards compatible).
    """
    if show_version:
        click.echo(f"videxer {version('videxer')}")
        ctx.exit()
    
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
    if ctx.params.get('log_level') is not None:
        provided_args['log_level'] = log_level

    # Merge config with provided args (CLI takes precedence)
    merged_config = merge_config_with_args(config, provided_args)

    # Use merged values
    output_dir = merged_config.get('output_dir')
    html_path = merged_config.get('html_path')
    json_path = merged_config.get('json_path')
    generate_thumbnails = merged_config.get('generate_thumbnails', False)
    generate_motion_thumbnails = merged_config.get('generate_motion_thumbnails', False)
    generate_transcodes = merged_config.get('generate_transcodes', False)
    log_level = merged_config.get('log_level', log_level)

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

    # Setup logging to output dir and stdout
    setup_logging(output_dir, level=log_level)
    logger = get_logger()

    # Log hardware acceleration status
    hw_accel = _get_hardware_accelerator()
    if hw_accel:
        logger.info(f"Hardware acceleration enabled: {hw_accel.name} (encoder: {hw_accel.encoder})")
    else:
        logger.info("Hardware acceleration not available - using software encoding")

    logger.info(f"Scanning media directory: {input_dir}")
    structure = detect_media_structure(input_dir)
    logger.info(f"Detected structure: {structure.value}")

    write_index_files(input_dir, html_path, json_path, generate_thumbnails, generate_motion_thumbnails, generate_transcodes)

    html_file = html_path or (output_dir / "index.html")
    json_file = json_path or (output_dir / "index.json")

    logger.info("Generated files:")
    logger.info(f"  HTML: {html_file}")
    logger.info(f"  JSON: {json_file}")
    logger.info(f"Open {html_file} in your browser to view the media library.")

    # Save current configuration for future runs
    save_config(input_dir, merged_config)
