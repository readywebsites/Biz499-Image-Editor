import logging
import requests
from django.core.files.base import ContentFile

logger = logging.getLogger(__name__)

class FigmaConverter:
    """
    Converts a raw Figma document JSON into a new format containing a background
    image and a simplified JSON for text elements.
    """

    def __init__(self, figma_document, figma_service, file_key, target_node_id=None):
        self.document = figma_document
        self.figma_service = figma_service
        self.file_key = file_key
        self.target_node_id = target_node_id

    def _find_node_by_id(self, node, target_id):
        if not node:
            return None
        if node.get("id") == target_id:
            return node
        if "children" in node:
            for child in node["children"]:
                found = self._find_node_by_id(child, target_id)
                if found:
                    return found
        return None

    def convert(self):
        """Main entry point for the conversion process."""
        logger.info(f"Starting conversion for file key '{self.file_key}'...")
        
        target_frame = None
        if self.target_node_id:
            target_frame = self._find_node_by_id(self.document.get("document", {}), self.target_node_id)
            if target_frame:
                logger.info(f"Found target frame by node-id '{self.target_node_id}': '{target_frame.get('name')}'")
            else:
                logger.warning(f"Could not find node with ID '{self.target_node_id}'. Falling back to main frame.")

        if not target_frame:
            target_frame = self._find_main_frame(self.document.get("document", {}))
            
        if not target_frame:
            raise ValueError("No suitable Frame found in the Figma file.")
        logger.info(f"Found target frame: '{target_frame.get('name')}' (ID: {target_frame.get('id')})")

        # 1. Render the entire frame as a background image
        background_image_url = self.figma_service.export_node_as_png(self.file_key, target_frame.get('id'))
        if not background_image_url:
            raise ValueError("Could not export background image from Figma.")

        try:
            response = requests.get(background_image_url, timeout=30)
            response.raise_for_status()
            background_image_content = ContentFile(response.content, name=f"{target_frame.get('id')}.png")
        except requests.RequestException as e:
            logger.error(f"Failed to download background image: {e}")
            raise

        # 2. Extract only text nodes for the simplified JSON
        text_elements = self._extract_text_nodes(target_frame)
        
        simplified_json = {
            "width": target_frame.get('absoluteBoundingBox', {}).get('width', 0),
            "height": target_frame.get('absoluteBoundingBox', {}).get('height', 0),
            "elements": text_elements,
        }

        logger.info("Successfully processed document into background image and text elements.")
        
        return {
            "background_image": background_image_content,
            "template_data": simplified_json,
            "width": simplified_json['width'],
            "height": simplified_json['height'],
        }

    def _find_main_frame(self, start_node):
        # Find first frame on first canvas
        if not start_node.get("children"):
            return None
        canvas = start_node.get("children", [])[0]
        for node in canvas.get("children", []):
            if node.get("type") == "FRAME":
                return node
        return None

    def _extract_text_nodes(self, start_node):
        text_nodes = []
        
        def find_text(node, parent_x=0, parent_y=0):
            if not node or not node.get("visible", True):
                return

            bbox = node.get("absoluteBoundingBox", {})
            
            if node.get("type") == "TEXT":
                text_nodes.append(self._process_text_node(node, parent_x, parent_y))

            # Recursively process children, passing the current node's absolute coordinates
            if "children" in node:
                for child in node["children"]:
                    find_text(child, bbox.get('x', 0), bbox.get('y', 0))

        # The root frame's coordinates are the reference
        root_bbox = start_node.get("absoluteBoundingBox", {})
        find_text(start_node, root_bbox.get('x', 0), root_bbox.get('y', 0))
        return text_nodes

    def _process_text_node(self, node, parent_x, parent_y):
        bbox = node.get("absoluteBoundingBox", {})
        style = node.get("style", {})
        
        # Calculate position relative to the main frame
        x = bbox.get("x", 0) - parent_x
        y = bbox.get("y", 0) - parent_y

        return {
            "id": node.get("id"),
            "type": "TEXT",
            "content": node.get("characters", ""),
            "x": x,
            "y": y,
            "width": bbox.get("width", 0),
            "height": bbox.get("height", 0),
            "rotation": node.get("rotation", 0) * -1,
            "opacity": node.get("opacity", 1),
            "style": {
                "fontFamily": style.get("fontFamily", "Inter"),
                "fontWeight": style.get("fontWeight", 400),
                "fontSize": style.get("fontSize", 12),
                "textAlignHorizontal": style.get("textAlignHorizontal", "LEFT"),
                "textAlignVertical": style.get("textAlignVertical", "TOP"),
                "letterSpacing": style.get("letterSpacing", 0),
                "lineHeightPx": style.get("lineHeightPx", style.get("fontSize", 12)),
                "color": self._format_color(self._find_solid_fill_color(node.get("fills", []))),
            }
        }

    def _find_solid_fill_color(self, fills):
        if not fills: return None
        for fill in fills:
            if fill.get("type") == "SOLID" and fill.get("visible", True):
                return fill.get("color")
        return None

    def _format_color(self, color):
        if not color: return "rgba(0,0,0,1)" # Default to black if no color found
        r = int(color.get("r", 0) * 255)
        g = int(color.get("g", 0) * 255)
        b = int(color.get("b", 0) * 255)
        a = color.get("a", 1)
        return f"rgba({r},{g},{b},{a})"