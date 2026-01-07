"""Markdown file writer tool for exporting content."""

import logging
from datetime import datetime
from pathlib import Path
from typing import Annotated

from pydantic import Field

logger = logging.getLogger("youtube_agent.writer")


def write_markdown_file(
    content: Annotated[str, Field(description="Markdown content to write to the file")],
    filename: Annotated[
        str,
        Field(description="Output filename (e.g., 'summary.md' or 'research-notes.md')"),
    ],
    output_dir: Annotated[
        str,
        Field(description="Output directory relative to current working directory"),
    ] = "output",
) -> str:
    """Write markdown content to a file.

    Creates the output directory if it doesn't exist.

    :param content: The markdown content to write
    :param filename: The output filename (should end with .md)
    :param output_dir: Directory to write to (default: 'output')
    :return: Confirmation message with file path
    """
    try:
        # Ensure filename has .md extension
        if not filename.endswith(".md"):
            filename = f"{filename}.md"

        # Create output directory
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Write the file
        file_path = output_path / filename
        file_path.write_text(content, encoding="utf-8")

        logger.debug("Wrote markdown file: %s", file_path)
        return f"Successfully wrote {len(content)} characters to {file_path}"

    except Exception as e:
        logger.error("Failed to write markdown file: %s", e)
        return f"Error writing file: {e}"


def write_timestamped_markdown(
    content: Annotated[str, Field(description="Markdown content to write to the file")],
    prefix: Annotated[
        str,
        Field(description="Filename prefix (e.g., 'research' becomes 'research_20240115_143022.md')"),
    ] = "notes",
    output_dir: Annotated[
        str,
        Field(description="Output directory relative to current working directory"),
    ] = "output",
) -> str:
    """Write markdown content to a timestamped file.

    Creates a unique filename using the current timestamp to avoid overwrites.

    :param content: The markdown content to write
    :param prefix: Filename prefix (timestamp will be appended)
    :param output_dir: Directory to write to (default: 'output')
    :return: Confirmation message with file path
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{prefix}_{timestamp}.md"
    return write_markdown_file(content, filename, output_dir)
