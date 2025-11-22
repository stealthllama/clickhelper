#!/usr/bin/env python3
"""
ClickHelper - ClickHelp Project Management and Backup Tool

This script manages ClickHelp projects and publications, supporting:
- Publishing publications with specified visibility and tags
- Exporting publications to PDF format (triggers PDF generation in ClickHelp)
- Downloading PDFs from ClickHelp storage
- Uploading PDFs to Tribble for document ingestion
- Backing up projects to AWS S3 with automated retention management

Configuration is managed via YAML file using a project-based format.

Workflows:
- publish: Publishes publications and triggers PDF exports (no downloads)
- tribble-upload: Downloads PDFs from ClickHelp and uploads to Tribble
- backup: Creates and uploads project backups to S3
- all: Runs all workflows in sequence

Usage:
    python clickhelper.py publish              # Run publication workflow
    python clickhelper.py tribble-upload       # Run Tribble upload workflow
    python clickhelper.py backup               # Run backup workflow
    python clickhelper.py all                  # Run all workflows (default)
    python clickhelper.py --config custom.yaml # Use custom config file
"""

import os
import sys
import logging
import argparse

# Import workflow functions from the clickhelper package
from clickhelper import (
    run_publications,
    run_tribble_upload,
    run_backup,
    run_all_workflows
)

# Environment variables should be set directly in the environment
# For local development: export variables in your shell
# For GitHub Actions: configure as repository secrets
# See .env.example for required variables

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('clickhelper.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


def parse_arguments():
    """
    Parse command line arguments.

    Returns:
        Parsed arguments
    """
    parser = argparse.ArgumentParser(
        description='ClickHelper - ClickHelp Project Management and Backup Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run publication workflow (publish and export PDFs)
  python clickhelper.py publish

  # Run Tribble upload workflow
  python clickhelper.py tribble-upload

  # Run backup workflow (backup to S3)
  python clickhelper.py backup

  # Run all workflows (default if no command specified)
  python clickhelper.py all

  # Specify custom config file
  python clickhelper.py --config custom_config.yaml
        """
    )

    parser.add_argument(
        'command',
        nargs='?',
        choices=['publish', 'tribble-upload', 'backup', 'all'],
        default='all',
        help='Workflow to run (default: all)'
    )

    parser.add_argument(
        '-c', '--config',
        default='config.yaml',
        help='Path to YAML configuration file (default: config.yaml)'
    )

    return parser.parse_args()


def main():
    """Main execution function."""
    # Parse command line arguments
    args = parse_arguments()

    # Get config file path
    config_file = os.getenv('CONFIG_FILE', args.config)

    # Check if config file exists
    if not os.path.exists(config_file):
        logger.error(f"Configuration file not found: {config_file}")
        logger.info("Tip: Use --config to specify a different config file")
        sys.exit(1)

    # Dispatch to appropriate workflow
    logger.info(f"Using configuration from: {config_file}")

    if args.command == 'publish':
        run_publications(config_file)
    elif args.command == 'tribble-upload':
        run_tribble_upload(config_file)
    elif args.command == 'backup':
        run_backup(config_file)
    elif args.command == 'all':
        run_all_workflows(config_file)


if __name__ == "__main__":
    main()
