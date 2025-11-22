"""
ClickHelper - ClickHelp Project Management and Backup Tool

This module provides classes for managing ClickHelp projects and publications:
- ClickHelpExporter: Handles API operations with ClickHelp portal
- ClickHelpProject: Represents a ClickHelp project with publications
- ClickHelpPublication: Represents a publication with export/upload capabilities
- TribbleUploader: Handles uploading PDFs to Tribble
- S3BackupUploader: Handles uploading backups to AWS S3
- ConfigLoader: Loads and parses YAML configuration files
"""

import os
import sys
import time
import json
import logging
import requests
import yaml
from datetime import datetime
from typing import Optional, Dict, Any, List
from requests.auth import HTTPBasicAuth
import boto3
from botocore.exceptions import ClientError

# Configure logging
logger = logging.getLogger(__name__)


class ClickHelpClient:
    """
    ClickHelp API client for managing projects, publications, and exports.

    Provides comprehensive API access for:
    - Publishing and managing publications
    - Exporting PDFs
    - Managing projects and backups
    - Task monitoring and status tracking
    """

    def __init__(self, portal_url: str, username: str, api_key: str):
        """
        Initialize ClickHelp exporter.

        Args:
            portal_url: Base URL of the ClickHelp portal (e.g., 'https://docs.dragos.com')
            username: ClickHelp account username
            api_key: ClickHelp API key
        """
        self.portal_url = portal_url.rstrip('/')
        self.username = username
        self.api_key = api_key
        self.auth = HTTPBasicAuth(username, api_key)
        self.session = requests.Session()
        self.session.auth = self.auth

    # ============================================================================
    # PDF Export Methods
    # ============================================================================

    def export_publication_pdf(self, project_id: str, publication_id: str, title: str,
                               export_preset_name: str = "Default") -> Dict[str, Any]:
        """
        Start PDF export for a publication.

        Args:
            project_id: The ClickHelp project ID (not used in API endpoint)
            publication_id: The publication ID to export
            title: The publication title for output filename
            export_preset_name: Export preset name for customization (default: "Default")

        Returns:
            Task information including task_key for tracking progress
        """
        endpoint = f"{self.portal_url}/api/v1/projects/{publication_id}?action=export"

        payload = {
            "format": "Pdf",
            "exportPresetName": export_preset_name,
            "outputFileName": f"Storage/Exported/{title}.pdf"
        }

        logger.info(f"Starting PDF export for publication {publication_id}")

        try:
            response = self.session.post(endpoint, json=payload)
            response.raise_for_status()

            result = json.loads(response.content.decode('utf-8-sig'))
            logger.info(f"Export task started. Task key: {result.get('taskKey')}")
            return result

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to start export: {e}")
            raise

    # ============================================================================
    # Task Management Methods
    # ============================================================================

    def get_task_status(self, task_key: str) -> Dict[str, Any]:
        """
        Check the status of an export task.

        Args:
            task_key: The task key returned from export_publication_pdf

        Returns:
            Task status information
        """
        endpoint = f"{self.portal_url}/api/v1/tasks/{task_key}"

        try:
            response = self.session.get(endpoint)
            response.raise_for_status()
            return json.loads(response.content.decode('utf-8-sig'))

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get task status: {e}")
            raise

    def wait_for_task(self, task_key: str, task_type: str = "task",
                     max_wait: int = 600, poll_interval: int = 10) -> Dict[str, Any]:
        """
        Wait for a task to complete (export, publish, backup, etc.).

        Args:
            task_key: The task key to monitor
            task_type: Type of task for logging (e.g., "export", "publish", "backup")
            max_wait: Maximum time to wait in seconds (default: 10 minutes)
            poll_interval: Time between status checks in seconds

        Returns:
            Final task status
        """
        start_time = time.time()

        logger.info(f"Waiting for {task_type} task {task_key} to complete...")

        while time.time() - start_time < max_wait:
            try:
                status = self.get_task_status(task_key)
            except requests.exceptions.HTTPError as e:
                # If we get a 404, the task might have completed and been removed
                if e.response.status_code == 404:
                    logger.warning(f"Task {task_key} not found (404). Task may have already completed.")
                    raise Exception(f"Task {task_key} not found. Check if task completed earlier or task key is invalid.")
                raise

            # ClickHelp API response format:
            # - isSucceeded: null (in progress), true (success), false (failed)
            # - isWorking: true (in progress), false (completed)
            # - overallProgress: current progress value
            # - maxOverallProgress: maximum progress value (typically 100)
            # - statusText: detailed status message

            is_succeeded = status.get('isSucceeded')
            is_working = status.get('isWorking', False)
            overall_progress = status.get('overallProgress', 0)
            max_progress = status.get('maxOverallProgress', 100)
            status_text = status.get('statusText', '')
            task_name = status.get('taskName', task_type)

            # Log progress
            progress_pct = int(overall_progress / max_progress * 100) if max_progress > 0 else 0
            logger.info(f"Task '{task_name}': {overall_progress}/{max_progress} ({progress_pct}%)")
            if status_text:
                # Clean up HTML tags from status text for cleaner logging
                clean_status = status_text.replace('<br/>', ' | ').strip()
                logger.info(f"  Status: {clean_status}")

            # Check if task is complete (isSucceeded is not null AND progress is at max)
            if is_succeeded is not None and overall_progress >= max_progress:
                if is_succeeded:
                    logger.info(f"{task_type.capitalize()} completed successfully")
                    return status
                else:
                    error_msg = status_text or "Task failed"
                    logger.error(f"{task_type.capitalize()} failed: {error_msg}")
                    raise Exception(f"{task_type.capitalize()} task failed: {error_msg}")

            # Task still in progress
            time.sleep(poll_interval)

        raise TimeoutError(f"{task_type.capitalize()} task did not complete within {max_wait} seconds")

    def wait_for_export(self, task_key: str, max_wait: int = 600,
                       poll_interval: int = 10) -> Dict[str, Any]:
        """
        Wait for export task to complete.
        (Wrapper for backward compatibility)

        Args:
            task_key: The task key to monitor
            max_wait: Maximum time to wait in seconds (default: 10 minutes)
            poll_interval: Time between status checks in seconds

        Returns:
            Final task status
        """
        return self.wait_for_task(task_key, "export", max_wait, poll_interval)

    def download_pdf(self, download_url: str, output_path: str) -> str:
        """
        Download the exported PDF file.

        Args:
            download_url: URL to download the PDF from
            output_path: Local path to save the PDF

        Returns:
            Path to the downloaded file
        """
        logger.info(f"Downloading PDF to {output_path}")

        try:
            # Ensure download URL is absolute
            if not download_url.startswith('http'):
                download_url = f"{self.portal_url}{download_url}"

            response = self.session.get(download_url, stream=True)
            response.raise_for_status()

            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            # Download file
            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            logger.info(f"PDF downloaded successfully: {output_path}")
            return output_path

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to download PDF: {e}")
            raise

    # ============================================================================
    # Publication Management Methods
    # ============================================================================

    def update_publication(self, project_id: str, publication_id: str,
                          pub_name: str,
                          update_mode: str = "Partial",
                          visibility: str = "Restricted",
                          output_tags: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Update an existing publication with specified settings.

        This triggers a ClickHelp publish operation that updates the publication
        with the specified visibility, update mode, and output tags.

        Note: To create a NEW publication, use create_publication() instead.

        Args:
            project_id: The ClickHelp project ID
            publication_id: The publication ID to update
            pub_name: The publication name/title
            update_mode: "FullReplace" or "Partial" update (default: "Partial")
            visibility: "Public", "Restricted", or "Private" (default: "Restricted")
            output_tags: List of output tags to apply (default: None)

        Returns:
            Task information including task_key for tracking progress
        """
        endpoint = f"{self.portal_url}/api/v1/projects/{project_id}?action=publish"

        payload = {
            "updatedPubId": publication_id,
            "pubName": pub_name,
            "updateMode": update_mode,
            "isPublishOnlyReadyTopics": True,
            "pubVisibility": visibility
        }

        if output_tags:
            payload["outputTags"] = output_tags

        logger.info(f"Publishing publication {publication_id} (updateMode: {update_mode}, visibility: {visibility})")

        try:
            response = self.session.post(endpoint, json=payload)
            response.raise_for_status()

            result = json.loads(response.content.decode('utf-8-sig'))
            logger.info(f"Publish task started. Task key: {result.get('taskKey')}")
            return result

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to start publish: {e}")
            raise

    # ============================================================================
    # Project Management & Backup Methods
    # ============================================================================

    def backup_project(self, project_id: str, project_name: str) -> Dict[str, Any]:
        """
        Create a backup of a ClickHelp project.

        Args:
            project_id: The ClickHelp project ID
            project_name: Human-readable project name for the backup filename

        Returns:
            Task information including task_key for tracking progress
        """
        endpoint = f"{self.portal_url}/api/v1/projects/{project_id}?action=download"

        # Generate timestamped filename with DD-MM-YYYY_HH-MM-SS format
        timestamp = datetime.now().strftime("%d-%m-%Y_%H-%M-%S")
        output_filename = f"Storage/Backups/{project_id}-backup-{timestamp}.zip"

        payload = {
            "outputFileName": output_filename
        }

        logger.info(f"Starting backup for project {project_id} ({project_name})")

        try:
            response = self.session.post(endpoint, json=payload)
            response.raise_for_status()

            result = json.loads(response.content.decode('utf-8-sig'))
            task_key = result.get('taskKey')
            logger.info(f"Backup task started. Task key: {task_key}")

            # Store the output filename in the result for later retrieval
            result['outputFileName'] = output_filename
            return result

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to start backup: {e}")
            raise

    def get_all_projects_publications(self) -> List[Dict[str, Any]]:
        """
        Get all projects and publications from ClickHelp.

        Projects have parentId = null
        Publications have parentId = project_id

        Returns:
            List of all projects and publications with their metadata
        """
        endpoint = f"{self.portal_url}/api/v1/projects"

        logger.info("Fetching all projects and publications from ClickHelp")

        try:
            response = self.session.get(endpoint)
            response.raise_for_status()

            items = json.loads(response.content.decode('utf-8-sig'))

            # Separate projects and publications for logging
            projects = [item for item in items if item.get('parentId') is None]
            publications = [item for item in items if item.get('parentId') is not None]

            logger.info(f"Retrieved {len(projects)} project(s) and {len(publications)} publication(s)")
            return items

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get projects and publications: {e}")
            raise

    def create_publication(self, project_id: str, publication_id: str, pub_name: str,
                          visibility: str = "Restricted",
                          output_tags: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Create a new publication in ClickHelp.

        This creates a brand new publication that doesn't already exist in the project.

        Note: To update an EXISTING publication, use update_publication() instead.

        Args:
            project_id: The ClickHelp project ID
            publication_id: The publication ID to create
            pub_name: The publication name/title
            visibility: "Public", "Restricted", or "Private" (default: "Restricted")
            output_tags: List of output tags to apply (default: None)

        Returns:
            Task information including task_key for tracking progress
        """
        endpoint = f"{self.portal_url}/api/v1/projects/{project_id}?action=publish"

        payload = {
            "pubId": publication_id,
            "pubName": pub_name,
            "isPublishOnlyReadyTopics": True,
            "pubVisibility": visibility
        }

        if output_tags:
            payload["outputTags"] = output_tags

        logger.info(f"Creating new publication '{pub_name}' ({publication_id}) in project {project_id}")

        try:
            response = self.session.post(endpoint, json=payload)
            response.raise_for_status()

            result = json.loads(response.content.decode('utf-8-sig'))
            logger.info(f"Publication creation started. Task key: {result.get('taskKey')}")
            return result

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to create publication: {e}")
            raise

    def delete_storage_file(self, file_path: str) -> bool:
        """
        Delete a file from ClickHelp storage.

        Args:
            file_path: Storage file path (e.g., "Storage/Backups/old-backup.zip")

        Returns:
            True if deletion was successful
        """
        # Remove 'Storage/' prefix if present to get the relative path
        relative_path = file_path.replace('Storage/', '', 1).strip('/')

        endpoint = f"{self.portal_url}/api/v1/storage/{relative_path}"

        logger.info(f"Deleting file from storage: {relative_path}")

        try:
            response = self.session.delete(endpoint)
            response.raise_for_status()
            logger.info(f"Successfully deleted: {relative_path}")
            return True

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to delete storage file {relative_path}: {e}")
            raise

    def download_backup(self, file_path: str, output_path: str) -> str:
        """
        Download a backup file from ClickHelp storage using the file path.

        Args:
            file_path: Storage file path (e.g., "Storage/Backups/project-backup_2024-01-01.zip")
            output_path: Local path to save the backup file

        Returns:
            Path to the downloaded file
        """
        logger.info(f"Downloading backup from {file_path} to {output_path}")

        try:
            # Remove 'Storage/' prefix if present to get the relative path
            relative_path = file_path.replace('Storage/', '', 1).strip('/')

            # Use the storage API to get the file with base64 encoding
            endpoint = f"{self.portal_url}/api/v1/storage/{relative_path}"
            params = {"format": "base64"}

            logger.info(f"Retrieving backup from: {relative_path}")

            response = self.session.get(endpoint, params=params)
            response.raise_for_status()

            # Parse JSON response
            response_data = json.loads(response.content.decode('utf-8-sig'))

            # Extract base64 content from the response
            base64_content = response_data.get('content')
            if not base64_content:
                raise Exception("No 'content' field found in API response")

            # Decode base64 content
            import base64
            file_data = base64.b64decode(base64_content)

            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            # Write file
            with open(output_path, 'wb') as f:
                f.write(file_data)

            logger.info(f"Backup downloaded successfully: {output_path} ({len(file_data)} bytes)")
            return output_path

        except Exception as e:
            logger.error(f"Failed to download backup: {e}")
            raise


class ClickHelpProject:
    """Represents a ClickHelp project with publications."""

    def __init__(self, project_id: str, name: str, exporter: ClickHelpClient):
        """
        Initialize ClickHelp project.

        Args:
            project_id: The project ID
            name: Human-readable project name
            exporter: ClickHelpClient instance for API operations
        """
        self.project_id = project_id
        self.name = name
        self.exporter = exporter
        self.publications: List['ClickHelpPublication'] = []

    def add_publication(self, publication_id: str, title: str,
                       actions: Optional[List[Dict[str, Any]]] = None) -> 'ClickHelpPublication':
        """
        Add a publication to this project.

        Args:
            publication_id: The publication ID
            title: Human-readable publication title
            actions: List of action configurations to perform

        Returns:
            ClickHelpPublication instance
        """
        publication = ClickHelpPublication(
            publication_id=publication_id,
            title=title,
            project=self,
            actions=actions or []
        )
        self.publications.append(publication)
        return publication

    def backup_project(self, download_dir: str = "./downloads") -> str:
        """
        Create and download a backup of this project.

        Args:
            download_dir: Directory to save the backup file

        Returns:
            Path to the downloaded backup file
        """
        logger.info(f"Starting backup for project: {self.name}")

        # Start backup
        task_info = self.exporter.backup_project(
            project_id=self.project_id,
            project_name=self.name
        )

        # Wait for backup to complete
        task_key = task_info.get('taskKey')
        if not task_key:
            raise Exception("No task key returned from backup")

        task_status = self.exporter.wait_for_task(task_key, "backup")

        # Get the backup file path from ClickHelp storage
        output_filename = task_info.get('outputFileName')
        if not output_filename:
            raise Exception("No output filename in task result")

        # Generate local filename
        local_filename = os.path.basename(output_filename)
        local_path = os.path.join(download_dir, local_filename)

        # Download the backup
        backup_path = self.exporter.download_backup(output_filename, local_path)

        # Delete the backup file from ClickHelp storage after successful download
        try:
            self.exporter.delete_storage_file(output_filename)
            logger.info(f"Deleted backup file from ClickHelp storage: {output_filename}")
        except Exception as e:
            logger.warning(f"Failed to delete backup from ClickHelp storage: {e}")
            # Don't fail the backup if we can't delete the file

        logger.info(f"Project backup completed: {backup_path}")
        return backup_path

    def __repr__(self):
        return f"<ClickHelpProject {self.project_id}: {self.name} ({len(self.publications)} publications)>"


class ClickHelpPublication:
    """Represents a ClickHelp publication with export and upload capabilities."""

    def __init__(self, publication_id: str, title: str,
                 project: ClickHelpProject,
                 actions: Optional[List[Dict[str, Any]]] = None):
        """
        Initialize ClickHelp publication.

        Args:
            publication_id: The publication ID
            title: Human-readable publication title
            project: Parent ClickHelpProject instance
            actions: List of action configurations to perform
        """
        self.publication_id = publication_id
        self.title = title
        self.project = project
        self.actions = actions or []
        self._last_export_path: Optional[str] = None

    def publish(self, update_mode: str = "Partial",
               visibility: str = "Restricted",
               output_tags: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Publish this publication.

        Args:
            update_mode: "FullReplace" or "Partial" update
            visibility: "Public", "Restricted", or "Private"
            output_tags: List of output tags to apply

        Returns:
            Publish task result
        """
        logger.info(f"Publishing: {self.title}")
        task_info = self.project.exporter.update_publication(
            project_id=self.project.project_id,
            publication_id=self.publication_id,
            pub_name=self.title,
            update_mode=update_mode,
            visibility=visibility,
            output_tags=output_tags
        )

        # Wait for publish to complete
        task_key = task_info.get('taskKey')
        if task_key:
            task_status = self.project.exporter.wait_for_task(task_key, "publish")
            logger.info(f"Publication '{self.title}' updated successfully")
            return task_status

        return task_info

    def export_to_pdf(self, export_preset_name: str = "Default") -> Dict[str, Any]:
        """
        Export this publication to PDF (without downloading).

        Args:
            export_preset_name: Export preset name (default: "Default")

        Returns:
            Task status information
        """
        logger.info(f"Exporting to PDF: {self.title}")

        # Start export
        task_info = self.project.exporter.export_publication_pdf(
            project_id=self.project.project_id,
            publication_id=self.publication_id,
            title=self.title,
            export_preset_name=export_preset_name
        )

        # Wait for export to complete
        task_key = task_info.get('taskKey')
        if not task_key:
            raise Exception("No task key returned from export")

        task_status = self.project.exporter.wait_for_export(task_key)
        logger.info(f"PDF export completed for: {self.title}")
        return task_status

    def download_pdf(self, output_filename: Optional[str] = None,
                    download_dir: str = "./downloads") -> str:
        """
        Download this publication's PDF from ClickHelp storage.
        The PDF must have been previously exported using export_to_pdf().

        Args:
            output_filename: Name for the output PDF file
            download_dir: Directory to save the PDF

        Returns:
            Path to the downloaded PDF file
        """
        logger.info(f"Downloading PDF: {self.title}")

        # Construct the storage path for the PDF
        storage_path = f"storage/Exported/{self.title}.pdf"

        # Build the URL with format=base64 query parameter
        endpoint = f"{self.project.exporter.portal_url}/api/v1/{storage_path}"
        params = {"format": "base64"}

        logger.info(f"Retrieving PDF from: {storage_path}")

        try:
            # Make GET request to retrieve base64-encoded PDF
            response = self.project.exporter.session.get(endpoint, params=params)
            response.raise_for_status()

            # Parse JSON response
            response_data = json.loads(response.content.decode('utf-8-sig'))

            # Extract base64 content from the response
            base64_content = response_data.get('content')
            if not base64_content:
                raise Exception("No 'content' field found in API response")

            # Get filename from response (use as fallback if output_filename not provided)
            api_filename = response_data.get('fileName')

            # Decode base64 content
            import base64
            pdf_data = base64.b64decode(base64_content)

            # Generate filename if not provided
            if not output_filename:
                # Use API filename if available, otherwise use publication_id
                if api_filename:
                    output_filename = api_filename
                else:
                    output_filename = f"{self.publication_id}.pdf"

            # Ensure .pdf extension
            if not output_filename.endswith('.pdf'):
                output_filename += '.pdf'

            # Save the PDF to the output path
            output_path = os.path.join(download_dir, output_filename)

            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else download_dir, exist_ok=True)

            with open(output_path, 'wb') as f:
                f.write(pdf_data)

            self._last_export_path = output_path
            logger.info(f"PDF downloaded successfully: {self._last_export_path} ({len(pdf_data)} bytes)")
            return self._last_export_path

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to download PDF from {storage_path}: {e}")
            raise
        except Exception as e:
            logger.error(f"Error processing PDF download: {e}")
            raise

    def upload_to_tribble(self, tribble_uploader: 'TribbleUploader',
                         label: Optional[str] = None,
                         pdf_path: Optional[str] = None,
                         wait_for_processing: bool = True) -> Dict[str, Any]:
        """
        Upload this publication's PDF to Tribble.

        Args:
            tribble_uploader: TribbleUploader instance
            label: Label for the document in Tribble (defaults to publication title)
            pdf_path: Path to PDF file (uses last exported PDF if not provided)
            wait_for_processing: Whether to wait for Tribble processing to complete

        Returns:
            Upload result including job_id
        """
        # Use provided path or last export path
        file_path = pdf_path or self._last_export_path
        if not file_path:
            raise ValueError("No PDF file available. Run export_to_pdf() first or provide pdf_path.")

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"PDF file not found: {file_path}")

        # Use provided label or publication title
        doc_label = label or self.title

        logger.info(f"Uploading to Tribble: {self.title} -> {doc_label}")

        # Upload to Tribble
        upload_result = tribble_uploader.upload_pdf(
            file_path=file_path,
            label=doc_label
        )

        # Optionally wait for processing
        if wait_for_processing and upload_result.get('success'):
            job_id = upload_result.get('response', {}).get('job_id')
            if job_id:
                try:
                    tribble_uploader.wait_for_processing(job_id)
                except TimeoutError as e:
                    logger.warning(f"Processing timeout: {e}")

        return upload_result

    def execute_actions(self, tribble_uploader: Optional['TribbleUploader'] = None,
                       download_dir: str = "./downloads",
                       wait_for_processing: bool = True) -> Dict[str, Any]:
        """
        Execute all configured actions for this publication.

        Args:
            tribble_uploader: TribbleUploader instance (required if upload_tribble action is configured)
            download_dir: Directory to save exported PDFs
            wait_for_processing: Whether to wait for Tribble processing

        Returns:
            Dictionary with results of all actions
        """
        results = {
            'publication_id': self.publication_id,
            'title': self.title,
            'actions': []
        }

        for action_config in self.actions:
            action_type = action_config.get('type')
            action_result = {'type': action_type, 'success': False}

            try:
                if action_type == 'publish':
                    logger.info(f"Action: Publish {self.title}")
                    task_info = self.publish(
                        update_mode=action_config.get('update_mode', 'Partial'),
                        visibility=action_config.get('visibility', 'Restricted'),
                        output_tags=action_config.get('output_tags')
                    )
                    action_result['success'] = True
                    action_result['task_key'] = task_info.get('taskKey')

                elif action_type == 'export_pdf':
                    logger.info(f"Action: Export PDF {self.title}")
                    task_status = self.export_to_pdf(
                        export_preset_name=action_config.get('export_preset_name', 'Default')
                    )
                    action_result['success'] = True
                    action_result['task_status'] = task_status

                elif action_type == 'download_pdf':
                    logger.info(f"Action: Download PDF {self.title}")
                    pdf_path = self.download_pdf(
                        output_filename=action_config.get('output_filename'),
                        download_dir=download_dir
                    )
                    action_result['success'] = True
                    action_result['pdf_path'] = pdf_path

                elif action_type == 'upload_tribble':
                    if not tribble_uploader:
                        raise ValueError("TribbleUploader required for upload_tribble action")

                    logger.info(f"Action: Upload to Tribble {self.title}")
                    upload_result = self.upload_to_tribble(
                        tribble_uploader=tribble_uploader,
                        label=action_config.get('label'),
                        wait_for_processing=wait_for_processing
                    )
                    action_result['success'] = upload_result.get('success', False)
                    action_result['job_id'] = upload_result.get('response', {}).get('job_id')

                else:
                    logger.warning(f"Unknown action type: {action_type}")
                    action_result['error'] = f"Unknown action type: {action_type}"

            except Exception as e:
                logger.error(f"Action failed: {action_type} - {e}")
                action_result['error'] = str(e)

            results['actions'].append(action_result)

        return results

    def __repr__(self):
        return f"<ClickHelpPublication {self.publication_id}: {self.title}>"


class TribbleUploader:
    """Handles uploading PDF files to Tribble using the Document Ingest API."""

    def __init__(self, api_token: str, user_email: str, base_url: str = "https://my.tribble.ai"):
        """
        Initialize Tribble uploader.

        Args:
            api_token: Tribble External Content Management API token
            user_email: Valid Tribble user email (used as "Created By" field)
            base_url: Tribble API base URL (defaults to https://my.tribble.ai)
        """
        self.api_token = api_token
        self.user_email = user_email
        self.base_url = base_url.rstrip('/')
        self.upload_endpoint = f"{self.base_url}/api/external/upload"
        self.status_endpoint = f"{self.base_url}/api/external/upload/status"

    def upload_pdf(self, file_path: str, label: str) -> Dict[str, Any]:
        """
        Upload a PDF file to Tribble for document ingestion.

        Args:
            file_path: Local path to the PDF file to upload
            label: Label/name for the document in Tribble

        Returns:
            Upload response including job_id for status tracking
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"PDF file not found: {file_path}")

        headers = {
            "Authorization": f"Bearer {self.api_token}"
        }

        # Prepare multipart form data
        files = {
            'file': (os.path.basename(file_path), open(file_path, 'rb'), 'application/pdf')
        }

        data = {
            'metadata': json.dumps({"label": label}),
            'user': self.user_email
        }

        logger.info(f"Uploading PDF to Tribble: {file_path} (label: {label})")

        try:
            response = requests.post(
                self.upload_endpoint,
                headers=headers,
                files=files,
                data=data
            )
            response.raise_for_status()

            result = response.json()

            if result.get('success'):
                job_id = result.get('response', {}).get('job_id')
                logger.info(f"PDF uploaded successfully. Job ID: {job_id}")
                return result
            else:
                error_msg = result.get('error', 'Unknown error')
                logger.error(f"Upload failed: {error_msg}")
                raise Exception(f"Tribble upload failed: {error_msg}")

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to upload PDF to Tribble: {e}")
            raise
        finally:
            # Close file handle
            if 'file' in files:
                files['file'][1].close()

    def check_status(self, job_id: str) -> Dict[str, Any]:
        """
        Check the status of a document ingest job.

        Args:
            job_id: Job ID returned from upload_pdf

        Returns:
            Status response with current processing state
        """
        headers = {
            "Authorization": f"Bearer {self.api_token}"
        }

        params = {
            "job_id": job_id
        }

        logger.info(f"Checking status for job: {job_id}")

        try:
            response = requests.get(
                self.status_endpoint,
                headers=headers,
                params=params
            )
            response.raise_for_status()

            result = response.json()

            if result.get('success'):
                status = result.get('response', {}).get('status')
                logger.info(f"Job {job_id} status: {status}")
                return result
            else:
                error_msg = result.get('error', 'Unknown error')
                logger.error(f"Status check failed: {error_msg}")
                raise Exception(f"Status check failed: {error_msg}")

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to check job status: {e}")
            raise

    def wait_for_processing(self, job_id: str, max_wait: int = 600,
                           poll_interval: int = 10) -> Dict[str, Any]:
        """
        Wait for document processing to complete.

        Args:
            job_id: Job ID to monitor
            max_wait: Maximum time to wait in seconds (default: 10 minutes)
            poll_interval: Time between status checks in seconds

        Returns:
            Final status response
        """
        start_time = time.time()

        logger.info(f"Waiting for job {job_id} to complete processing...")

        while time.time() - start_time < max_wait:
            status_response = self.check_status(job_id)
            status = status_response.get('response', {}).get('status')

            elapsed = time.time() - start_time
            elapsed_str = f"{int(elapsed // 60)}m {int(elapsed % 60)}s"

            if status == 'processed':
                logger.info(f"Job {job_id} completed successfully (elapsed: {elapsed_str})")
                return status_response
            elif status == 'processing':
                logger.info(f"Job {job_id} still processing... waiting {poll_interval}s (elapsed: {elapsed_str})")
                time.sleep(poll_interval)
            else:
                logger.warning(f"Unknown status for job {job_id}: {status} (elapsed: {elapsed_str})")
                time.sleep(poll_interval)

        raise TimeoutError(f"Job {job_id} did not complete within {max_wait} seconds")


class S3BackupUploader:
    """Handles uploading ClickHelp project backups to AWS S3 with retention management."""

    def __init__(self, bucket_name: str, aws_access_key_id: Optional[str] = None,
                 aws_secret_access_key: Optional[str] = None, region: str = 'us-east-1'):
        """
        Initialize S3 backup uploader.

        Args:
            bucket_name: S3 bucket name for storing backups
            aws_access_key_id: AWS access key ID (optional, uses default credentials if not provided)
            aws_secret_access_key: AWS secret access key (optional, uses default credentials if not provided)
            region: AWS region (default: us-east-1)
        """
        self.bucket_name = bucket_name
        self.region = region

        # Initialize S3 client with credentials if provided, otherwise use default credentials
        if aws_access_key_id and aws_secret_access_key:
            self.s3_client = boto3.client(
                's3',
                aws_access_key_id=aws_access_key_id,
                aws_secret_access_key=aws_secret_access_key,
                region_name=region
            )
        else:
            # Use default credentials from environment or AWS config
            self.s3_client = boto3.client('s3', region_name=region)

        logger.info(f"S3BackupUploader initialized for bucket: {bucket_name}")

    def upload_backup(self, local_file_path: str, s3_folder: str,
                     custom_filename: Optional[str] = None) -> Dict[str, Any]:
        """
        Upload a backup file to S3.

        Args:
            local_file_path: Path to the local backup file
            s3_folder: Folder name in S3 bucket (e.g., "My-Project")
            custom_filename: Optional custom filename (defaults to original filename)

        Returns:
            Upload result with S3 key and metadata
        """
        if not os.path.exists(local_file_path):
            raise FileNotFoundError(f"Backup file not found: {local_file_path}")

        # Use custom filename or original filename
        filename = custom_filename or os.path.basename(local_file_path)

        # Construct S3 key (path in bucket)
        s3_key = f"{s3_folder.rstrip('/')}/{filename}"

        logger.info(f"Uploading backup to S3: s3://{self.bucket_name}/{s3_key}")

        try:
            # Upload file to S3
            self.s3_client.upload_file(
                Filename=local_file_path,
                Bucket=self.bucket_name,
                Key=s3_key
            )

            # Get file size for logging
            file_size = os.path.getsize(local_file_path)
            logger.info(f"Successfully uploaded {file_size} bytes to S3: {s3_key}")

            return {
                'success': True,
                's3_key': s3_key,
                'bucket': self.bucket_name,
                'file_size': file_size,
                's3_url': f"s3://{self.bucket_name}/{s3_key}"
            }

        except ClientError as e:
            error_msg = f"Failed to upload to S3: {e}"
            logger.error(error_msg)
            return {
                'success': False,
                'error': error_msg
            }
        except Exception as e:
            error_msg = f"Unexpected error uploading to S3: {e}"
            logger.error(error_msg)
            return {
                'success': False,
                'error': error_msg
            }

    def list_backups(self, s3_folder: str) -> List[Dict[str, Any]]:
        """
        List all backup files in a specific S3 folder.

        Args:
            s3_folder: Folder name in S3 bucket

        Returns:
            List of backup file metadata
        """
        prefix = f"{s3_folder.rstrip('/')}/"

        logger.info(f"Listing backups in s3://{self.bucket_name}/{prefix}")

        try:
            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix=prefix
            )

            backups = []
            if 'Contents' in response:
                for obj in response['Contents']:
                    backups.append({
                        'key': obj['Key'],
                        'size': obj['Size'],
                        'last_modified': obj['LastModified'],
                        'filename': os.path.basename(obj['Key'])
                    })

            logger.info(f"Found {len(backups)} backup(s) in {prefix}")
            return backups

        except ClientError as e:
            logger.error(f"Failed to list backups: {e}")
            raise

    def cleanup_old_backups(self, s3_folder: str, retention_count: int = 30) -> int:
        """
        Delete old backup files, keeping only the most recent N backups.

        Args:
            s3_folder: Folder name in S3 bucket
            retention_count: Number of most recent backups to retain (default: 30)

        Returns:
            Number of files deleted
        """
        logger.info(f"Cleaning up old backups in {s3_folder}, keeping {retention_count} most recent")

        try:
            # Get list of all backups
            backups = self.list_backups(s3_folder)

            if len(backups) <= retention_count:
                logger.info(f"Found {len(backups)} backup(s), no cleanup needed (retention: {retention_count})")
                return 0

            # Sort backups by last modified date (newest first)
            backups_sorted = sorted(backups, key=lambda x: x['last_modified'], reverse=True)

            # Keep the first N (most recent), delete the rest
            backups_to_keep = backups_sorted[:retention_count]
            backups_to_delete = backups_sorted[retention_count:]

            logger.info(f"Keeping {len(backups_to_keep)} most recent backup(s)")
            logger.info(f"Deleting {len(backups_to_delete)} old backup(s)")

            deleted_count = 0
            for backup in backups_to_delete:
                s3_key = backup['key']
                last_modified = backup['last_modified']
                logger.info(f"Deleting old backup: {s3_key} (modified: {last_modified})")

                try:
                    self.s3_client.delete_object(
                        Bucket=self.bucket_name,
                        Key=s3_key
                    )
                    deleted_count += 1
                    logger.info(f"Deleted: {s3_key}")

                except ClientError as e:
                    logger.error(f"Failed to delete {s3_key}: {e}")
                    continue

            logger.info(f"Cleanup complete. Deleted {deleted_count} old backup(s)")
            return deleted_count

        except Exception as e:
            logger.error(f"Error during backup cleanup: {e}")
            raise


def get_env_var(var_name: str, required: bool = True) -> Optional[str]:
    """
    Get environment variable value.

    Args:
        var_name: Name of the environment variable
        required: Whether the variable is required

    Returns:
        Value of the environment variable or None if not required and not found
    """
    value = os.getenv(var_name)
    if required and not value:
        logger.error(f"Required environment variable {var_name} is not set")
        raise ValueError(f"Required environment variable {var_name} is not set")
    return value


class ConfigLoader:
    """Loads and parses YAML configuration file."""

    @staticmethod
    def load_config(config_path: str) -> Dict[str, Any]:
        """
        Load configuration from YAML file.

        Args:
            config_path: Path to YAML configuration file

        Returns:
            Configuration dictionary
        """
        try:
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)
                logger.info(f"Configuration loaded from {config_path}")
                return config
        except FileNotFoundError:
            logger.error(f"Configuration file not found: {config_path}")
            raise
        except yaml.YAMLError as e:
            logger.error(f"Failed to parse YAML configuration: {e}")
            raise

    @staticmethod
    def _build_actions_from_publication(pub_config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Build action list from publication configuration properties.

        This handles the new YAML format where actions are derived from properties
        like 'update', 'visibility', 'export', and 'output_tags'.

        Args:
            pub_config: Publication configuration dictionary

        Returns:
            List of action dictionaries
        """
        actions = []

        # Always create a publish action if update/visibility/output_tags are specified
        if 'update' in pub_config or 'visibility' in pub_config or 'output_tags' in pub_config:
            publish_action = {
                'type': 'publish',
                'update_mode': pub_config.get('update', 'Partial'),
                'visibility': pub_config.get('visibility', 'Private'),
                'output_tags': pub_config.get('output_tags', [])
            }
            actions.append(publish_action)

        # Add export_pdf action if export flag is True
        if pub_config.get('export', False):
            # Generate filename from title if available
            title = pub_config.get('title', '')
            # Clean title for filename: remove only special chars that aren't allowed in filenames
            # Allow spaces, alphanumeric chars, underscores, hyphens, and periods
            filename = ''.join(c if c.isalnum() or c in (' ', '_', '-', '.') else '' for c in title)
            filename = filename.strip()  # Remove leading/trailing whitespace
            if filename and not filename.endswith('.pdf'):
                filename = f"{filename}.pdf"

            # Add export action (triggers PDF generation in ClickHelp)
            export_action = {
                'type': 'export_pdf',
                'export_preset_name': pub_config.get('export_preset_name', 'Default')
            }
            actions.append(export_action)

            # Add download action (downloads PDF from ClickHelp storage)
            download_action = {
                'type': 'download_pdf',
                'output_filename': filename if filename else None
            }
            actions.append(download_action)

            # If export is enabled, also add upload_tribble action
            # (assuming exported PDFs should be uploaded to Tribble)
            upload_action = {
                'type': 'upload_tribble',
                'label': pub_config.get('title', '')
            }
            actions.append(upload_action)

        return actions

    @staticmethod
    def build_projects_from_config(config: Dict[str, Any],
                                   exporter: ClickHelpClient) -> List[ClickHelpProject]:
        """
        Build ClickHelpProject objects from configuration.

        The configuration uses a project-based structure where each top-level key
        (e.g., 'release-notes', 'deployment-guide') represents a ClickHelp project.
        Each project contains publications that can be published, exported to PDF,
        and uploaded to Tribble.

        Args:
            config: Configuration dictionary
            exporter: ClickHelpClient instance

        Returns:
            List of ClickHelpProject instances
        """
        projects = []

        # Filter out known config sections to find project definitions
        config_sections = {'clickhelp', 'tribble', 's3_backup', 'settings'}
        project_keys = [key for key in config.keys() if key not in config_sections]

        for project_key in project_keys:
            project_data = config[project_key]

            if not isinstance(project_data, dict):
                logger.warning(f"Skipping project {project_key}: not a dictionary")
                continue

            # The project key IS the ClickHelp project ID
            project_id = project_key
            project_name = project_key.replace('-', ' ').title()

            # Create the project
            project = ClickHelpProject(
                project_id=project_id,
                name=project_name,
                exporter=exporter
            )

            # Each key in the project data is a publication
            for pub_id, pub_config in project_data.items():
                if not isinstance(pub_config, dict):
                    logger.warning(f"Skipping publication {pub_id} in project {project_id}: not a dictionary")
                    continue

                pub_title = pub_config.get('title', pub_id)

                # Generate actions from properties
                actions = ConfigLoader._build_actions_from_publication(pub_config)

                if actions:  # Only add publication if it has actions
                    project.add_publication(
                        publication_id=pub_id,
                        title=pub_title,
                        actions=actions
                    )

            # Only add project if it has publications
            if project.publications:
                projects.append(project)
                logger.info(f"Loaded project: {project}")

        return projects


def run_publications(config_file: str = 'config.yaml'):
    """
    Run publication workflow: publish publications and export PDFs.

    Args:
        config_file: Path to YAML configuration file (default: 'config.yaml')
    """
    logger.info("=" * 80)
    logger.info("ClickHelper - Publication Workflow")
    logger.info("=" * 80)

    # Load YAML configuration
    config = ConfigLoader.load_config(config_file)

    # Extract configuration sections
    clickhelp_config = config.get('clickhelp', {})
    settings = config.get('settings', {})

    # ClickHelp credentials (from config or environment)
    clickhelp_portal_url = clickhelp_config.get('portal_url') or get_env_var('CLICKHELP_PORTAL_URL')
    clickhelp_username = get_env_var('CLICKHELP_USERNAME')
    clickhelp_api_key = get_env_var('CLICKHELP_API_KEY')

    # Settings
    download_dir = settings.get('download_dir', './downloads')

    # Initialize ClickHelp client
    exporter = ClickHelpClient(
        portal_url=clickhelp_portal_url,
        username=clickhelp_username,
        api_key=clickhelp_api_key
    )

    # Create download directory
    os.makedirs(download_dir, exist_ok=True)

    # Get all existing projects and publications from ClickHelp
    logger.info("Fetching existing projects and publications from ClickHelp...")
    all_items = exporter.get_all_projects_publications()

    # Build lookup dictionaries for quick access
    existing_projects = {item['id']: item for item in all_items if item.get('parentId') is None}
    existing_publications = {item['id']: item for item in all_items if item.get('parentId') is not None}

    logger.info(f"Found {len(existing_projects)} existing project(s) and {len(existing_publications)} existing publication(s)")

    # Verify and create publications as needed
    # First, identify all publications defined in config
    config_sections = {'clickhelp', 'tribble', 's3_backup', 'settings'}
    project_keys = [key for key in config.keys() if key not in config_sections]

    for project_key in project_keys:
        project_data = config[project_key]

        if not isinstance(project_data, dict):
            continue

        project_id = project_key

        # Check if project exists
        if project_id not in existing_projects:
            logger.warning(f"Project '{project_id}' not found in ClickHelp - publications cannot be created without a valid project")
            continue

        # Check each publication in this project
        for pub_id, pub_config in project_data.items():
            if not isinstance(pub_config, dict):
                continue

            # Check if publication exists
            if pub_id not in existing_publications:
                logger.info(f"Publication '{pub_id}' not found in project '{project_id}' - creating it now...")

                # Extract parameters from config
                pub_title = pub_config.get('title', pub_id)
                visibility = pub_config.get('visibility', 'Restricted')
                output_tags = pub_config.get('output_tags')

                try:
                    # Create the publication
                    task_info = exporter.create_publication(
                        project_id=project_id,
                        publication_id=pub_id,
                        pub_name=pub_title,
                        visibility=visibility,
                        output_tags=output_tags
                    )

                    # Wait for creation to complete
                    task_key = task_info.get('taskKey')
                    if task_key:
                        logger.info(f"Waiting for publication creation to complete (task: {task_key})...")
                        max_wait = settings.get('max_export_wait', 600)
                        poll_interval = settings.get('poll_interval', 10)

                        task_status = exporter.wait_for_task(
                            task_key=task_key,
                            max_wait_seconds=max_wait,
                            poll_interval=poll_interval
                        )

                        if task_status.get('status') == 'Success':
                            logger.info(f"  ✓ Publication '{pub_id}' created successfully")
                            # Add to existing_publications so we don't try to create it again
                            existing_publications[pub_id] = {'id': pub_id, 'parentId': project_id}
                        else:
                            logger.error(f"  ✗ Publication creation failed: {task_status.get('errorMessage', 'Unknown error')}")

                except Exception as e:
                    logger.error(f"Failed to create publication '{pub_id}': {e}")
                    continue

    # Build projects from configuration
    projects = ConfigLoader.build_projects_from_config(config, exporter)

    logger.info(f"Loaded {len(projects)} project(s)")

    # Process each project's publications (publish and export_pdf actions only)
    total_publications = sum(len(p.publications) for p in projects)
    current_pub = 0

    for project in projects:
        logger.info("-" * 80)
        logger.info(f"Processing project: {project.name} ({project.project_id})")
        logger.info(f"Publications: {len(project.publications)}")

        for publication in project.publications:
            current_pub += 1
            logger.info("=" * 80)
            logger.info(f"[{current_pub}/{total_publications}] {publication.title}")
            logger.info("=" * 80)

            try:
                # Execute only publish and export_pdf actions (no download)
                for action_config in publication.actions:
                    action_type = action_config.get('type')

                    if action_type == 'publish':
                        logger.info(f"Action: Publish {publication.title}")
                        task_info = publication.publish(
                            update_mode=action_config.get('update_mode', 'Partial'),
                            visibility=action_config.get('visibility', 'Restricted'),
                            output_tags=action_config.get('output_tags')
                        )
                        logger.info(f"  ✓ Publish: SUCCESS (task_key: {task_info.get('taskKey')})")

                    elif action_type == 'export_pdf':
                        logger.info(f"Action: Export PDF {publication.title}")
                        task_status = publication.export_to_pdf(
                            export_preset_name=action_config.get('export_preset_name', 'Default')
                        )
                        logger.info(f"  ✓ Export PDF: SUCCESS")

            except Exception as e:
                logger.error(f"Failed to process publication {publication.title}: {e}")
                continue

    logger.info("=" * 80)
    logger.info("Publication workflow completed!")
    logger.info("=" * 80)


def run_tribble_upload(config_file: str = 'config.yaml'):
    """
    Run Tribble upload workflow: upload PDFs to Tribble.

    Args:
        config_file: Path to YAML configuration file (default: 'config.yaml')
    """
    logger.info("=" * 80)
    logger.info("ClickHelper - Tribble Upload Workflow")
    logger.info("=" * 80)

    # Load YAML configuration
    config = ConfigLoader.load_config(config_file)

    # Extract configuration sections
    clickhelp_config = config.get('clickhelp', {})
    tribble_config = config.get('tribble', {})
    settings = config.get('settings', {})

    # ClickHelp credentials (from config or environment)
    clickhelp_portal_url = clickhelp_config.get('portal_url') or get_env_var('CLICKHELP_PORTAL_URL')
    clickhelp_username = get_env_var('CLICKHELP_USERNAME')
    clickhelp_api_key = get_env_var('CLICKHELP_API_KEY')

    # Tribble credentials (from config or environment)
    tribble_base_url = tribble_config.get('base_url') or get_env_var('TRIBBLE_BASE_URL', required=False) or 'https://my.tribble.ai'
    tribble_api_token = get_env_var('TRIBBLE_API_TOKEN')
    tribble_user_email = get_env_var('TRIBBLE_USER_EMAIL')

    # Settings
    download_dir = settings.get('download_dir', './downloads')
    wait_for_processing = settings.get('wait_for_processing', True)

    # Initialize ClickHelp client
    exporter = ClickHelpClient(
        portal_url=clickhelp_portal_url,
        username=clickhelp_username,
        api_key=clickhelp_api_key
    )

    # Initialize Tribble uploader
    uploader = TribbleUploader(
        api_token=tribble_api_token,
        user_email=tribble_user_email,
        base_url=tribble_base_url
    )

    # Create download directory
    os.makedirs(download_dir, exist_ok=True)

    # Build projects from configuration
    projects = ConfigLoader.build_projects_from_config(config, exporter)

    logger.info(f"Loaded {len(projects)} project(s)")

    # Process each project's publications (upload_tribble actions only)
    total_publications = sum(len(p.publications) for p in projects)
    current_pub = 0

    for project in projects:
        logger.info("-" * 80)
        logger.info(f"Processing project: {project.name} ({project.project_id})")
        logger.info(f"Publications: {len(project.publications)}")

        for publication in project.publications:
            current_pub += 1
            logger.info("=" * 80)
            logger.info(f"[{current_pub}/{total_publications}] {publication.title}")
            logger.info("=" * 80)

            try:
                # Execute download_pdf and upload_tribble actions
                for action_config in publication.actions:
                    action_type = action_config.get('type')

                    if action_type == 'download_pdf':
                        logger.info(f"Action: Download PDF {publication.title}")
                        pdf_path = publication.download_pdf(
                            output_filename=action_config.get('output_filename'),
                            download_dir=download_dir
                        )
                        logger.info(f"  ✓ Download PDF: SUCCESS ({pdf_path})")

                    elif action_type == 'upload_tribble':
                        logger.info(f"Action: Upload to Tribble {publication.title}")
                        upload_result = publication.upload_to_tribble(
                            tribble_uploader=uploader,
                            label=action_config.get('label'),
                            wait_for_processing=wait_for_processing
                        )

                        if upload_result.get('success'):
                            job_id = upload_result.get('response', {}).get('job_id')
                            logger.info(f"  ✓ Upload to Tribble: SUCCESS (job_id: {job_id})")
                        else:
                            logger.error(f"  ✗ Upload to Tribble: FAILED")

            except Exception as e:
                logger.error(f"Failed to process publication {publication.title}: {e}")
                continue

    logger.info("=" * 80)
    logger.info("Tribble upload workflow completed!")
    logger.info("=" * 80)


def run_backup(config_file: str = 'config.yaml'):
    """
    Run backup workflow: backup projects to S3.

    Args:
        config_file: Path to YAML configuration file (default: 'config.yaml')
    """
    logger.info("=" * 80)
    logger.info("ClickHelper - Backup Workflow")
    logger.info("=" * 80)

    # Load YAML configuration
    config = ConfigLoader.load_config(config_file)

    # Extract configuration sections
    clickhelp_config = config.get('clickhelp', {})
    s3_backup_config = config.get('s3_backup', {})
    settings = config.get('settings', {})

    # ClickHelp credentials (from config or environment)
    clickhelp_portal_url = clickhelp_config.get('portal_url') or get_env_var('CLICKHELP_PORTAL_URL')
    clickhelp_username = get_env_var('CLICKHELP_USERNAME')
    clickhelp_api_key = get_env_var('CLICKHELP_API_KEY')

    # S3 backup configuration
    s3_backup_enabled = s3_backup_config.get('enabled', False)
    s3_retention_count = s3_backup_config.get('retention_count', 30)

    # Settings - use ./backups directory for backup files
    download_dir = settings.get('backup_dir', './backups')

    if not s3_backup_enabled:
        logger.warning("S3 backup is not enabled in configuration. Exiting.")
        return

    # Initialize ClickHelp client
    exporter = ClickHelpClient(
        portal_url=clickhelp_portal_url,
        username=clickhelp_username,
        api_key=clickhelp_api_key
    )

    # Initialize S3 backup uploader
    aws_access_key_id = get_env_var('AWS_ACCESS_KEY_ID', required=False)
    aws_secret_access_key = get_env_var('AWS_SECRET_ACCESS_KEY', required=False)
    aws_s3_bucket = get_env_var('AWS_S3_BUCKET_NAME')
    aws_region = get_env_var('AWS_REGION', required=False) or 'us-east-1'

    s3_uploader = S3BackupUploader(
        bucket_name=aws_s3_bucket,
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
        region=aws_region
    )

    # Create download directory
    os.makedirs(download_dir, exist_ok=True)

    # Build projects from configuration
    projects = ConfigLoader.build_projects_from_config(config, exporter)

    logger.info(f"Loaded {len(projects)} project(s)")

    # Get project configurations to check backup settings
    projects_config = config.get('projects', [])

    for idx, project in enumerate(projects):
        # Get the corresponding project config
        project_config = projects_config[idx] if idx < len(projects_config) else {}
        backup_config = project_config.get('backup', {})

        logger.info("-" * 80)
        logger.info(f"Backing up project: {project.name}")

        try:
            # Create and download backup
            backup_path = project.backup_project(download_dir=download_dir)

            # Get S3 folder name from config (default to project_id)
            s3_folder = backup_config.get('s3_folder', project.project_id)

            # Upload to S3
            logger.info(f"Uploading backup to S3 folder: {s3_folder}")
            upload_result = s3_uploader.upload_backup(
                local_file_path=backup_path,
                s3_folder=s3_folder
            )

            if upload_result.get('success'):
                logger.info(f"✓ Backup uploaded successfully: {upload_result.get('s3_url')}")

                # Clean up old backups based on retention policy (keep N most recent)
                logger.info(f"Cleaning up old backups, keeping {s3_retention_count} most recent")
                deleted_count = s3_uploader.cleanup_old_backups(
                    s3_folder=s3_folder,
                    retention_count=s3_retention_count
                )
                logger.info(f"Removed {deleted_count} old backup(s)")

                # Clean up local backup file
                if os.path.exists(backup_path):
                    os.remove(backup_path)
                    logger.info(f"Removed local backup file: {backup_path}")
            else:
                logger.error(f"✗ Failed to upload backup: {upload_result.get('error')}")

        except Exception as e:
            logger.error(f"Failed to backup project {project.name}: {e}")
            continue

    logger.info("=" * 80)
    logger.info("Backup workflow completed!")
    logger.info("=" * 80)


def run_all_workflows(config_file: str = 'config.yaml'):
    """
    Run all workflows in sequence: publish, tribble-upload, and backup.

    Args:
        config_file: Path to YAML configuration file (default: 'config.yaml')
    """
    logger.info("=" * 80)
    logger.info("ClickHelper - Running All Workflows")
    logger.info("=" * 80)

    # Run all three workflows in sequence
    run_publications(config_file)
    run_tribble_upload(config_file)
    run_backup(config_file)

    logger.info("=" * 80)
    logger.info("All workflows completed!")
    logger.info("=" * 80)


# Export all public classes and functions
__all__ = [
    'ClickHelpClient',
    'ClickHelpProject',
    'ClickHelpPublication',
    'TribbleUploader',
    'S3BackupUploader',
    'ConfigLoader',
    'get_env_var',
    'run_publications',
    'run_tribble_upload',
    'run_backup',
    'run_all_workflows'
]
