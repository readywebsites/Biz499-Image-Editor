import logging
import json
import os
from django.core.management.base import BaseCommand
from editorapp.models import FigmaImportJob, Template
from editorapp.services.figma_service import FigmaService
from editorapp.services.figma_converter import FigmaConverter

logger = logging.getLogger(__name__)

def inject_src_into_fallback(node):
    if not isinstance(node, dict):
        return
    
    # Check if this node has an image fill
    is_image = False
    for fill in node.get('fills', []):
        if isinstance(fill, dict) and fill.get('type') == 'IMAGE':
            is_image = True
            break
            
    if is_image or node.get('type') == 'IMAGE':
        node_id = node.get('id')
        mock_srcs = {
            "4:15": "https://figma-alpha-api.s3.us-west-2.amazonaws.com/images/67798b8c-5004-48ed-a1c4-5e70673fddbb",
            "4:9": "https://figma-alpha-api.s3.us-west-2.amazonaws.com/images/324fb421-901f-4030-a64e-e5f15da47bf0"
        }
        s3_url = mock_srcs.get(node_id)
        if s3_url:
            import os
            import requests
            from django.conf import settings
            
            media_dir = os.path.join(settings.MEDIA_ROOT, 'figma_images')
            os.makedirs(media_dir, exist_ok=True)
            
            safe_filename = node_id.replace(':', '_') + ".png"
            local_path = os.path.join(media_dir, safe_filename)
            
            try:
                response = requests.get(s3_url, timeout=15)
                response.raise_for_status()
                with open(local_path, 'wb') as f:
                    f.write(response.content)
                node['src'] = f"{settings.MEDIA_URL}figma_images/{safe_filename}"
                logger.info(f"Fallback downloaded and saved image '{node_id}' -> '{local_path}'")
            except Exception as e:
                logger.error(f"Failed to cache fallback image '{node_id}': {e}")
                node['src'] = s3_url
        else:
            node['src'] = "https://figma-alpha-api.s3.us-west-2.amazonaws.com/images/placeholder"
        node['type'] = 'IMAGE'
        
    for child in node.get('children', []):
        inject_src_into_fallback(child)

class Command(BaseCommand):
    help = 'Processes pending Figma import jobs.'

    def handle(self, *args, **options):
        import os
        import time
        from django.conf import settings
        
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

        # Create lock
        try:
            with open(lock_file, 'w') as f:
                f.write(str(os.getpid()))
        except Exception as e:
            self.stdout.write(f'Failed to create lock file: {e}')
            return

        try:
            pending_jobs = FigmaImportJob.objects.filter(status='pending')
            if not pending_jobs:
                self.stdout.write(self.style.SUCCESS('No pending Figma import jobs to process.'))
                return

            self.stdout.write(f"Found {len(pending_jobs)} pending job(s). Starting processing...")

            for job in pending_jobs:
                job.refresh_from_db()
                if job.status != 'pending':
                    continue
                    
                job.status = 'processing'
                job.save()
                self.stdout.write(f"Processing job for template '{job.name}'...")

                try:
                    figma_service = FigmaService()
                    file_key = figma_service.extract_file_key_from_url(job.figma_url)
                    if not file_key:
                        raise ValueError("Invalid Figma URL, could not extract file key.")

                    # Fallback to local mock document ONLY if the URL specifically uses 'mock_file_key'
                    if file_key == 'mock_file_key':
                        self.stdout.write("Mock file key detected. Loading local fallback template...")
                        fallback_path = os.path.join(os.path.dirname(settings.BASE_DIR), 'latest_template.json')
                        if os.path.exists(fallback_path):
                            with open(fallback_path, 'r', encoding='utf-8') as f:
                                template_data = json.load(f)
                            inject_src_into_fallback(template_data)
                            self.stdout.write(self.style.WARNING(f"Fell back to local mock document for job '{job.name}'"))
                            
                            from django.core.files.base import ContentFile
                            mock_image_path = os.path.join(os.path.dirname(settings.BASE_DIR), 'test.png')
                            if os.path.exists(mock_image_path):
                                with open(mock_image_path, 'rb') as img_f:
                                    background_image_content = ContentFile(img_f.read(), name="mock_bg.png")
                            else:
                                background_image_content = ContentFile(b"", name="mock_bg.png")
                                
                            conversion_result = {
                                'background_image': background_image_content,
                                'template_data': template_data,
                                'width': template_data.get('width', 2000),
                                'height': template_data.get('height', 2000),
                            }
                        else:
                            raise FileNotFoundError("Local mock latest_template.json not found.")
                    else:
                        # Real Figma API call via FigmaImporter
                        from editorapp.services.figma_importer import FigmaImporter
                        importer = FigmaImporter()
                        result = importer.import_from_url(job.figma_url, job.name)

                        new_template = Template.objects.create(
                            name=job.name,
                            figma_url=job.figma_url,
                            template_data=result['template_data'],
                            background_image=result['background_image_path'],
                            width=result['width'],
                            height=result['height'],
                            status='published'
                        )

                    job.status = 'completed'
                    job.template = new_template
                    job.error_message = None
                    job.save()
                    self.stdout.write(self.style.SUCCESS(f"Successfully imported template '{job.name}' (ID: {new_template.id})"))

                except Exception as e:
                    error_message = f"Figma import failed: {e}"
                    logger.error(error_message, exc_info=True)
                    job.status = 'failed'
                    job.error_message = str(e)
                    job.save()
                    self.stdout.write(self.style.ERROR(f"Failed to import template '{job.name}'. Error: {e}"))
        finally:
            # Remove lock
            if os.path.exists(lock_file):
                try:
                    os.remove(lock_file)
                except OSError:
                    pass
