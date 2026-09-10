import os
import time
import logging
from django.core.management.base import BaseCommand
from django.conf import settings
from editorapp.models import FigmaImportJob
from editorapp.services.figma_runner import process_figma_job

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Processes pending Figma import jobs.'

    def add_arguments(self, parser):
        parser.add_argument('--job-id', type=int, help='Process a specific FigmaImportJob ID')

    def handle(self, *args, **options):
        specific_id = options.get('job_id')
        if specific_id:
            self.stdout.write(f"Processing specific FigmaImportJob ID {specific_id}...")
            process_figma_job(specific_id)
            self.stdout.write(self.style.SUCCESS("Finished processing specified job."))
            return

        lock_file = os.path.join(settings.BASE_DIR, 'figma_import.lock')
        
        # Check lock
        if os.path.exists(lock_file):
            mtime = os.path.getmtime(lock_file)
            if time.time() - mtime > 600: # 10 minutes stale lock
                try:
                    os.remove(lock_file)
                except OSError:
                    pass
            else:
                self.stdout.write('Another figma import process is already running. Exiting.')
                return

        try:
            with open(lock_file, 'w') as f:
                f.write(str(os.getpid()))
        except Exception as e:
            self.stdout.write(f'Failed to create lock file: {e}')
            return

        try:
            pending_jobs = list(FigmaImportJob.objects.filter(status='pending'))
            if not pending_jobs:
                self.stdout.write(self.style.SUCCESS('No pending Figma import jobs to process.'))
                return

            self.stdout.write(f"Found {len(pending_jobs)} pending job(s). Starting processing...")
            for job in pending_jobs:
                self.stdout.write(f"Processing job ID {job.id} for '{job.name}'...")
                process_figma_job(job.id)
                job.refresh_from_db()
                if job.status == 'completed':
                    self.stdout.write(self.style.SUCCESS(f"Successfully processed job ID {job.id}"))
                else:
                    self.stdout.write(self.style.ERROR(f"Job ID {job.id} status: {job.status} (Error: {job.error_message})"))
        finally:
            if os.path.exists(lock_file):
                try:
                    os.remove(lock_file)
                except OSError:
                    pass
