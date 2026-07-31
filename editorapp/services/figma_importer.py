import os
import json
import logging
from django.conf import settings
from django.core.files.base import ContentFile
from urllib.parse import urlparse, parse_qs
from .figma_service import FigmaService
from .figma_converter import FigmaConverter
from ..management.commands.process_figma_imports import inject_src_into_fallback

logger = logging.getLogger(__name__)

class FigmaImporter:
    """
    Orchestrates the Figma import workflow:
    - Extracts File ID and Node ID from Figma URL.
    - Fetches design structure from Figma REST API.
    - Downloads rendered frame PNG into media/templates/.
    - Converts Figma response into simplified JSON of text elements.
    """

    @staticmethod
    def parse_figma_url(url):
        if not url:
            return None, None
            
        figma_service = FigmaService()
        file_key = figma_service.extract_file_key_from_url(url)
        node_id = None
        
        try:
            parsed_url = urlparse(url)
            query_params = parse_qs(parsed_url.query)
            if 'node-id' in query_params:
                node_id = query_params['node-id'][0]
                # Normalise hyphen to colon for node IDs
                node_id = node_id.replace('-', ':')
        except Exception as e:
            logger.warning(f"Error parsing query parameters from Figma URL: {e}")
            
        return file_key, node_id

    def import_from_url(self, url, template_name="Figma Import"):
        """
        Fetches design and renders/converts it.
        Returns a dict with template data properties ready to populate Template model.
        """
        file_key, node_id = self.parse_figma_url(url)
        if not file_key:
            raise ValueError("Could not extract Figma File Key from the provided URL.")
            
        # Fallback to local mock document if mock_file_key is detected
        if file_key == 'mock_file_key':
            logger.info("Mock file key detected in figma_importer. Loading local fallback template...")
            fallback_path = os.path.join(os.path.dirname(settings.BASE_DIR), 'latest_template.json')
            if os.path.exists(fallback_path):
                with open(fallback_path, 'r', encoding='utf-8') as f:
                    template_data = json.load(f)
                inject_src_into_fallback(template_data)
                
                mock_image_path = os.path.join(os.path.dirname(settings.BASE_DIR), 'test.png')
                if os.path.exists(mock_image_path):
                    with open(mock_image_path, 'rb') as img_f:
                        bg_content = img_f.read()
                else:
                    bg_content = b""
                
                conversion_result = {
                    'template_data': template_data,
                    'width': template_data.get('width', 2000),
                    'height': template_data.get('height', 2000),
                }
                bg_data = bg_content
            else:
                raise FileNotFoundError("Local mock latest_template.json not found.")
        else:
            # Real Figma API call
            figma_service = FigmaService()
            figma_document = figma_service.get_file(file_key)
            
            converter = FigmaConverter(
                figma_document=figma_document,
                figma_service=figma_service,
                file_key=file_key,
                target_node_id=node_id
            )
            
            conversion_result = converter.convert()
            # Read binary content of background image ContentFile
            bg_image_file = conversion_result['background_image']
            bg_data = bg_image_file.read()

        # 4. Save PNG to media/templates/
        templates_dir = os.path.join(settings.MEDIA_ROOT, 'templates')
        os.makedirs(templates_dir, exist_ok=True)
        
        # Generate safe filename
        safe_node_id = (node_id or "root").replace(':', '_')
        filename = f"{file_key}_{safe_node_id}.png"
        local_filepath = os.path.join(templates_dir, filename)
        
        # Write binary content to destination file path
        with open(local_filepath, 'wb') as f:
            f.write(bg_data)
                
        # Return results mapped for the Template model
        return {
            "name": template_name,
            "template_data": conversion_result['template_data'],
            "background_image_path": f"templates/{filename}",
            "width": conversion_result['width'],
            "height": conversion_result['height'],
        }
