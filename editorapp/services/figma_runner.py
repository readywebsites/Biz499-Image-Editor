import os
import re
import time
import logging
import threading
from django.conf import settings

logger = logging.getLogger(__name__)

def sanitize_error_message(error_str):
    """
    Sanitizes error messages to ensure no tokens, credentials, or sensitive headers
    are exposed in the database, UI, or API responses.
    """
    if not error_str:
        return "Unknown error occurred during Figma import."
    
    cleaned = str(error_str)
    # Mask Figma Personal Access Tokens (e.g. figd_..., figma_...)
    cleaned = re.sub(r'figd_[a-zA-Z0-9_\-]{20,}', '[TOKEN_REDACTED]', cleaned)
    cleaned = re.sub(r'figma_[a-zA-Z0-9_\-]{20,}', '[TOKEN_REDACTED]', cleaned)
    # Mask potential bearer tokens or raw hex/alphanumeric tokens > 30 chars
    cleaned = re.sub(r'(Bearer\s+)[a-zA-Z0-9_\-\.]{20,}', r'\1[REDACTED]', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'(X-Figma-Token:\s*)[^\s]+', r'\1[REDACTED]', cleaned, flags=re.IGNORECASE)
    return cleaned.strip()

def process_figma_job(job_id):
    """
    Executes a single Figma import job synchronously.
    Handles job state transitions (pending -> processing -> completed / failed),
    creates or updates the associated Template model, and ensures database connections
    are closed cleanly.
    """
    from django.db import connections, OperationalError
    from editorapp.models import FigmaImportJob, Template
    from editorapp.services.figma_importer import FigmaImporter

    # Retry with backoff to ensure database transaction is fully visible
    job = None
    for attempt in range(10):
        try:
            job = FigmaImportJob.objects.filter(id=job_id).first()
            if job:
                break
        except OperationalError:
            pass
        time.sleep(0.5)

    if not job:
        logger.warning(f"FigmaImportJob ID {job_id} not found after retrying.")
        return

    if job.status == 'processing':
        # Allow recovery if a previous worker crashed and job has been stuck for >10m
        from django.utils import timezone
        import datetime
        stale_threshold = timezone.now() - datetime.timedelta(minutes=10)
        if job.updated_at and job.updated_at > stale_threshold:
            logger.info(f"FigmaImportJob ID {job_id} is already actively processing. Skipping duplicate execution.")
            return
        logger.warning(f"FigmaImportJob ID {job_id} was stuck in 'processing' for >10 minutes. Resuming execution.")
    elif job.status == 'completed':
        logger.info(f"FigmaImportJob ID {job_id} is already completed. Skipping duplicate execution.")
        return

    try:
        # Mark job as processing
        job.status = 'processing'
        job.error_message = None
        job.save(update_fields=['status', 'error_message', 'updated_at'])
        logger.info(f"Starting background processing for FigmaImportJob ID {job_id} ('{job.name}')...")

        # Run the full importer
        importer = FigmaImporter()
        result = importer.import_from_url(job.figma_url, job.name)

        # Update existing linked template, or create a new published template
        template = job.template
        if template:
            template.name = job.name
            template.figma_url = job.figma_url
            template.template_data = result['template_data']
            template.background_image = result['background_image_path']
            template.width = result['width']
            template.height = result['height']
            template.status = 'published'
            template.save()
            logger.info(f"Updated existing Template ID {template.id} ('{template.name}') from job ID {job_id}.")
        else:
            template = Template.objects.create(
                name=job.name,
                figma_url=job.figma_url,
                template_data=result['template_data'],
                background_image=result['background_image_path'],
                width=result['width'],
                height=result['height'],
                status='published'
            )
            job.template = template
            logger.info(f"Created new Template ID {template.id} ('{template.name}') from job ID {job_id}.")

        # Mark job as completed
        job.status = 'completed'
        job.error_message = None
        job.save(update_fields=['status', 'error_message', 'template', 'updated_at'])
        element_count = len(result['template_data'].get('elements', []))
        logger.info(f"Successfully finished FigmaImportJob ID {job_id} with {element_count} elements.")

    except Exception as e:
        logger.error(f"Figma import failed for job ID {job_id}: {e}", exc_info=True)
        try:
            for attempt in range(5):
                try:
                    job = FigmaImportJob.objects.filter(id=job_id).first()
                    if job:
                        job.status = 'failed'
                        job.error_message = sanitize_error_message(str(e))
                        job.save(update_fields=['status', 'error_message', 'updated_at'])
                    break
                except OperationalError:
                    if attempt < 4:
                        time.sleep(0.3)
                    else:
                        raise
        except Exception as db_err:
            logger.error(f"Failed to persist error status for FigmaImportJob ID {job_id}: {db_err}")
    finally:
        connections.close_all()

def start_figma_import_background(job_id):
    """
    Dispatches a Figma import job to run in a background daemon thread.
    Ensures thread starts AFTER the database transaction commits so the job row
    is visible and not locked by the creating connection.
    """
    from django.db import transaction

    def _launch():
        thread = threading.Thread(
            target=process_figma_job,
            args=(job_id,),
            daemon=True,
            name=f"figma-import-job-{job_id}"
        )
        thread.start()
        logger.info(f"Dispatched Figma import job ID {job_id} to background thread '{thread.name}'.")
        return thread

    try:
        transaction.on_commit(_launch)
    except Exception:
        return _launch()

