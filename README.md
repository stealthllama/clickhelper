# ClickHelper

A Python tool for managing ClickHelp documentation projects with automated publishing, PDF export, Tribble integration, and AWS S3 backup capabilities.

## Features

- **Publication Management**: Publish ClickHelp publications with configurable visibility and output tags
- **Automatic Publication Creation**: Publications defined in config that don't exist are automatically created
- **PDF Export**: Export publications to PDF format
- **Tribble Integration**: Automatic upload to Tribble for AI-powered document search
- **S3 Backup**: Automated project backups to AWS S3 with retention policy
- **Batch Processing**: Process multiple projects and publications in a single run
- **Auto-Generated Actions**: Actions automatically generated from publication properties

## Prerequisites

- Python 3.7 or higher
- ClickHelp account with API access
- Tribble account with External Content Management API token (for Tribble uploads)
- AWS account with S3 access (for automated backups)

## Installation

1. Clone or download this repository

2. Install required dependencies:
```bash
pip install -r requirements.txt
```

## API Setup

### ClickHelp API

1. Log in to your ClickHelp portal
2. Go to Settings > API
3. Generate or copy your API key
4. Note your username

### Tribble API

1. Log in to your Tribble account at [my.tribble.ai](https://my.tribble.ai)
2. Navigate to **Settings > Manage API Tokens** in the Admin Console
3. Click on "Create New API Token"
4. Select "External Content Management Token"
5. Save the generated token securely

## Configuration

### YAML Configuration Structure

Each top-level key represents a **ClickHelp project**. Under each project, define the **publications** that belong to that project.

```yaml
# Global ClickHelp Configuration
clickhelp:
  portal_url: "https://docs.example.com"

# Global Tribble Configuration
tribble:
  base_url: "https://my.tribble.ai"

# S3 Backup Configuration
s3_backup:
  enabled: true
  retention_count: 30  # Keep the last X backups per project

# Global settings
settings:
  download_dir: "./downloads"
  backup_dir: "./backups"
  wait_for_export: true
  wait_for_processing: true
  max_wait: 600  # seconds - maximum wait time for all task status calls
  poll_interval: 10  # seconds

# Projects (each top-level key is a ClickHelp project ID)
release-notes:  # Project ID
  # Publications in this project
  dragos-platform-release-notes:  # Publication ID
    title: Release Notes
    update: Partial           # Update type: "Partial" or "Full"
    visibility: Restricted    # Visibility: "Public", "Restricted", or "Private"
    export: False            # Set to True to export PDF and upload to Tribble
    output_tags:
      - OnlineDoc
      - Platform_3.0

  export-dragos-platform-release-notes:  # Another publication
    title: Dragos Platform Release Notes
    update: Partial
    visibility: Private
    export: True            # Will auto-generate: publish, export_pdf, upload_tribble
    output_tags:
      - PrintedDoc
      - Platform_3.0

deployment-guide:  # Another project
  deployment-guide-3-0:
    title: Deployment Guide 3.0
    update: Partial
    visibility: Restricted
    export: False
    output_tags:
      - OnlineDoc
      - Platform_3.0
```

### Publication Properties

Each publication requires:
- `title`: Display name
- `update`: "Partial" or "Full"
- `visibility`: "Public", "Restricted", or "Private"
- `export`: `True` (export PDF + upload to Tribble) or `False` (publish only)
- `output_tags`: List of ClickHelp tags

### Auto-Generated Actions

Based on publication properties, actions are automatically generated:

| Configuration | Actions Generated |
|--------------|-------------------|
| `update`, `visibility`, `output_tags` | publish |
| `export: True` | publish → export_pdf → upload_tribble |
| `export: False` | publish only |

## Usage

### Set Environment Variables

```bash
# ClickHelp credentials
export CLICKHELP_USERNAME="your-username"
export CLICKHELP_API_KEY="your-api-key"

# Tribble credentials
export TRIBBLE_API_TOKEN="your-token"
export TRIBBLE_USER_EMAIL="your-email@company.com"

# AWS credentials (for S3 backup)
export AWS_ACCESS_KEY_ID="your-aws-access-key"
export AWS_SECRET_ACCESS_KEY="your-aws-secret-key"
export AWS_S3_BUCKET_NAME="your-bucket-name"
export AWS_REGION="us-east-1"  # Optional, defaults to us-east-1
```

### Run Workflows

```bash
# Run all workflows (default)
python clickhelper.py

# Run specific workflow
python clickhelper.py publish        # Publish and export only
python clickhelper.py tribble-upload # Upload PDFs to Tribble
python clickhelper.py backup         # Backup projects to S3

# Use custom config file
python clickhelper.py --config custom.yaml
```

## Examples

### Minimal Configuration

```yaml
clickhelp:
  portal_url: "https://docs.example.com"

user-guide:  # ClickHelp project ID
  user-guide-online:  # Publication ID
    title: User Guide
    update: Partial
    visibility: Restricted
    export: False
    output_tags:
      - OnlineDoc
```

### Publication with PDF Export

```yaml
admin-guide:
  export-admin-guide-pdf:
    title: Administrator Guide
    update: Partial
    visibility: Private
    export: True  # Generates: publish, export_pdf, upload_tribble actions
    output_tags:
      - PrintedDoc
      - Version_1.0
```

## Important Notes

### Project IDs
The YAML key **must exactly match** your ClickHelp project ID (case-sensitive):
```yaml
release-notes:  # ✅ Must match ClickHelp project ID exactly
```

### Publication IDs
The nested key represents your ClickHelp publication ID (case-sensitive):
```yaml
release-notes:
  dragos-platform-release-notes:  # Publication ID
    title: Release Notes
```

**Automatic Publication Creation**: If a publication defined in `config.yaml` does not exist in ClickHelp, it will be **automatically created** during the `publish` workflow. The publication will be created with the specified:
- Title
- Visibility (Public, Restricted, or Private)
- Output tags

This ensures your workflow can start fresh with new publications without manual setup in the ClickHelp UI.

### Workflows

1. **publish**: Publishes publications and exports PDFs
   - Automatically creates publications that don't exist in ClickHelp
   - Updates existing publications with configured settings
   - Exports PDFs for publications with `export: True`
2. **tribble-upload**: Uploads exported PDFs to Tribble
3. **backup**: Backs up projects to S3
4. **all** (default): Runs all three workflows in sequence

**Publication Workflow Details**:
When you run the `publish` workflow, ClickHelper will:
1. Fetch all existing projects and publications from ClickHelp (single API call)
2. For each publication in your config:
   - If it **doesn't exist**: Create it with the specified title, visibility, and output tags
   - If it **exists**: Update it with the current configuration
3. Proceed with publishing and PDF export as configured

This means you can define new publications in `config.yaml` and they will be automatically created on the first run.

### S3 Backup Retention

The S3 backup workflow uses a **count-based retention policy** instead of time-based:

- **`retention_count`**: Number of most recent backups to keep per project (default: 30)
- Backups are sorted by last modified date (newest first)
- Only the N most recent backups are retained
- Older backups are automatically deleted after new backups are uploaded

**Example:**
```yaml
s3_backup:
  enabled: true
  retention_count: 30  # Keep last 30 backups per project
```

This ensures you always have a consistent number of backup versions available, regardless of how frequently backups run.

## Logging

All operations are logged to:
- Console (stdout)
- `clickhelper.log` file in the current directory

## Troubleshooting

### "No projects found"
Check that your top-level keys aren't reserved names: `clickhelp`, `tribble`, `s3_backup`, `settings`

### "Project not found in ClickHelp"
Verify the YAML key exactly matches your ClickHelp project ID (case-sensitive)

### "Publication not found"
Verify the nested key exactly matches your ClickHelp publication ID (case-sensitive)

### "No actions generated"
Make sure you have at least `update`, `visibility`, or `output_tags` defined

## Architecture

- `ClickHelpClient`: ClickHelp API client for all ClickHelp operations (publishing, exports, backups, project management)
- `ClickHelpProject`: Manages projects and their publications
- `ClickHelpPublication`: Handles publishing, PDF export, and Tribble upload
- `TribbleUploader`: Handles Tribble document ingestion
- `S3BackupUploader`: Manages S3 backup uploads and retention
- `ConfigLoader`: YAML configuration parsing and project building

## License

[Your License Here]
