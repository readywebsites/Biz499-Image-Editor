import os
import json
import logging
from urllib.parse import urlparse, parse_qs
from django.conf import settings
from .figma_service import FigmaService
from .figma_converter import FigmaConverter

logger = logging.getLogger(__name__)

class FigmaImporter:
    """
    Orchestrates the Figma import workflow:
    - Extracts File ID and Node ID from Figma URL.
    - Fetches design structure from Figma REST API.
    - Uses FigmaConverter to parse all layers into editable elements.
    - Downloads images, vectors (SVGs), masked groups, and clean background.
    - Returns structured template data ready to populate the Template model.
    """

    @staticmethod
    def parse_figma_url(url):
        """Extracts (file_key, node_id) from a Figma URL."""
        if not url:
            return None, None

        file_key = FigmaService.extract_file_key_from_url(url)
        node_id = None

        try:
            parsed_url = urlparse(url)
            query_params = parse_qs(parsed_url.query)
            if 'node-id' in query_params:
                node_id = query_params['node-id'][0]
                # Normalise hyphen to colon for Figma node IDs (e.g. 4-15 -> 4:15)
                node_id = node_id.replace('-', ':')
        except Exception as e:
            logger.warning(f"Error parsing query parameters from Figma URL: {e}")

        return file_key, node_id

    def import_from_url(self, url, template_name="Figma Import", api_token=None):
        """
        Fetches design and converts it into fully editable template elements and assets.
        Returns a dict with template data properties ready to populate the Template model.
        """
        file_key, node_id = self.parse_figma_url(url)
        if not file_key:
            raise ValueError("Invalid Figma URL: Could not extract a valid Figma File Key from the provided URL.")

        logger.info(f"Importing Figma template '{template_name}' from file '{file_key}' (node-id: '{node_id}')...")

        # Check if local mock test key is specified for credential-free testing
        if file_key == 'mock_file_key':
            logger.info("Mock file key detected. Loading local template bundle...")
            bundle_dir = os.path.join(os.path.dirname(settings.BASE_DIR), 'template_bundle')
            if not os.path.exists(bundle_dir):
                bundle_dir = os.path.join(settings.BASE_DIR, '..', 'template_bundle')
            bundle_json = os.path.join(bundle_dir, 'template.json')
            if os.path.exists(bundle_json):
                with open(bundle_json, 'r', encoding='utf-8') as f:
                    template_data = json.load(f)
                
                # Copy bundle assets to media
                figma_images_dir = os.path.join(settings.MEDIA_ROOT, 'figma_images')
                templates_dir = os.path.join(settings.MEDIA_ROOT, 'template_backgrounds')
                os.makedirs(figma_images_dir, exist_ok=True)
                os.makedirs(templates_dir, exist_ok=True)

                import shutil
                for fname in os.listdir(bundle_dir):
                    src_f = os.path.join(bundle_dir, fname)
                    if os.path.isfile(src_f) and fname != 'template.json':
                        shutil.copyfile(src_f, os.path.join(figma_images_dir, fname))

                bg_src = os.path.join(bundle_dir, 'background.png')
                bg_name = f"mock_{file_key}_bg.png"
                if os.path.exists(bg_src):
                    shutil.copyfile(bg_src, os.path.join(templates_dir, bg_name))

                return {
                    "name": template_name,
                    "template_data": template_data,
                    "background_image_path": f"template_backgrounds/{bg_name}",
                    "width": template_data.get('width', 2000),
                    "height": template_data.get('height', 2000),
                }

        figma_service = FigmaService(api_token=api_token)

        # 1. Fetch document or specific node
        figma_document = None
        if node_id:
            try:
                logger.info(f"Fetching targeted node '{node_id}' from Figma API...")
                node_response = figma_service.get_file_node(file_key, node_id)
                if node_response and "nodes" in node_response and node_id in node_response["nodes"]:
                    figma_document = node_response
                    logger.info(f"Successfully fetched targeted node '{node_id}'.")
            except Exception as e:
                # If authentication or authorization failed, fail fast instead of retrying
                if hasattr(e, 'response') and getattr(e.response, 'status_code', None) in (401, 403):
                    raise
                logger.warning(f"Failed to fetch targeted node '{node_id}': {e}. Falling back to full document...")

        if not figma_document:
            logger.info(f"Fetching full Figma file '{file_key}'...")
            figma_document = figma_service.get_file(file_key)

        # 2. Run full converter
        converter = FigmaConverter(
            figma_document=figma_document,
            figma_service=figma_service,
            file_key=file_key,
            target_node_id=node_id,
            template_name=template_name
        )

        conversion_result = converter.convert()

        return {
            "name": template_name,
            "template_data": conversion_result["template_data"],
            "background_image_path": conversion_result["background_image_path"],
            "width": conversion_result["width"],
            "height": conversion_result["height"],
        }
