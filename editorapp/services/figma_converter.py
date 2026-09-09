import os
import re
import math
import shutil
import logging
import requests
from PIL import Image
from django.conf import settings

logger = logging.getLogger(__name__)

# Standard mapping of numeric weights to font weight names
FONT_WEIGHT_NAMES = {
    100: 'Thin',
    200: 'ExtraLight',
    300: 'Light',
    400: 'Regular',
    500: 'Medium',
    600: 'SemiBold',
    700: 'Bold',
    800: 'ExtraBold',
    900: 'Black',
}

def clean_node_id(node_id):
    """Replaces unsafe filesystem and URL characters in Figma node IDs."""
    if not node_id:
        return "root"
    return re.sub(r'[:;\\/*?\"<>| -]', '_', str(node_id))

def solid_fill_to_hex(fills):
    """Extracts the first visible solid fill color as a #rrggbb hex string."""
    if not fills or not isinstance(fills, list):
        return "#000000"
    for fill in fills:
        if isinstance(fill, dict) and fill.get("type") == "SOLID" and fill.get("visible", True):
            color = fill.get("color", {})
            r = int(round(color.get("r", 0) * 255))
            g = int(round(color.get("g", 0) * 255))
            b = int(round(color.get("b", 0) * 255))
            return f"#{r:02x}{g:02x}{b:02x}"
    return "#000000"

def get_node_rotation(node):
    """Calculates the rotation angle in degrees from node relativeTransform or rotation."""
    rel_transform = node.get("relativeTransform")
    if rel_transform and len(rel_transform) >= 2 and len(rel_transform[0]) >= 2:
        try:
            a = rel_transform[0][0]
            b = rel_transform[1][0]
            deg = round(math.degrees(math.atan2(b, a)), 2)
            return 0.0 if abs(deg) < 0.01 else deg
        except Exception:
            pass
    if "rotation" in node:
        try:
            deg = round(float(node.get("rotation", 0)), 2)
            return 0.0 if abs(deg) < 0.01 else deg
        except Exception:
            pass
    return 0.0

def is_mask_group(node):
    """Checks if a group or frame contains a mask layer as a child."""
    if node.get("type") in ("FRAME", "GROUP", "COMPONENT", "INSTANCE", "BOOLEAN_OPERATION"):
        for child in node.get("children", []):
            if child.get("isMask") is True:
                return True
    return False

def is_icon_node(node):
    """Checks if a node is named as an icon (contains a colon like 'ic:round-business-center')."""
    name = node.get("name", "")
    if ":" in name:
        parts = name.split(":")
        if len(parts) == 2 and len(parts[0]) > 1 and len(parts[1]) > 1:
            return True
    return False

def get_image_fill(node):
    """Returns the first visible IMAGE fill in a node's fills, if any."""
    fills = node.get("fills", [])
    if isinstance(fills, list):
        for fill in fills:
            if isinstance(fill, dict) and fill.get("type") == "IMAGE" and fill.get("visible", True):
                return fill
    return None

class FigmaConverter:
    """
    Converts a Figma document or frame node tree into editable template JSON and downloads all
    associated assets (images, vectors, masked groups, and generated background).
    
    Replicates the exact element extraction schema used by the Figma Template Exporter plugin.
    """

    CUSTOM_VECTOR_TYPES = {
        'VECTOR', 'BOOLEAN_OPERATION', 'STAR', 'LINE',
        'ELLIPSE', 'POLYGON', 'REGULAR_POLYGON'
    }

    def __init__(self, figma_document, figma_service, file_key, target_node_id=None, template_name="Figma Template"):
        self.document = figma_document
        self.figma_service = figma_service
        self.file_key = file_key
        self.target_node_id = target_node_id
        self.template_name = template_name

    def _find_node_by_id(self, node, target_id):
        """Recursively finds a node with the specified ID."""
        if not node or not isinstance(node, dict):
            return None
        if node.get("id") == target_id:
            return node
        for child in node.get("children", []):
            found = self._find_node_by_id(child, target_id)
            if found:
                return found
        return None

    def _find_main_frame(self, start_node):
        """Finds the first FRAME or canvas frame in the document."""
        if not start_node or not isinstance(start_node, dict):
            return None
        if start_node.get("type") == "FRAME":
            return start_node
        # Search canvas children
        children = start_node.get("children", [])
        if children:
            for child in children:
                if child.get("type") == "FRAME":
                    return child
                if child.get("type") == "CANVAS":
                    for canvas_child in child.get("children", []):
                        if canvas_child.get("type") == "FRAME":
                            return canvas_child
        return None

    def convert(self):
        """
        Main conversion pipeline:
        1. Locates the target frame.
        2. Traverses all layers bottom-to-top, classifying elements.
        3. Batch exports SVGs and PNGs from Figma API.
        4. Downloads image assets to media/figma_images/.
        5. Generates the clean background image.
        6. Assembles the final template_data structure.
        """
        logger.info(f"Starting conversion for Figma file '{self.file_key}', target node '{self.target_node_id}'...")

        # 1. Locate target frame
        target_frame = None
        doc_root = self.document

        # If fetched via get_file_node, the document might be inside nodes[target_node_id]['document']
        if isinstance(doc_root, dict) and "nodes" in doc_root:
            nodes_map = doc_root.get("nodes", {})
            if self.target_node_id and self.target_node_id in nodes_map:
                target_frame = nodes_map[self.target_node_id].get("document")
            elif nodes_map:
                first_node_data = next(iter(nodes_map.values()))
                target_frame = first_node_data.get("document")

        if not target_frame and "document" in doc_root:
            doc_root = doc_root.get("document", {})

        if not target_frame and self.target_node_id:
            target_frame = self._find_node_by_id(doc_root, self.target_node_id)
            if target_frame:
                logger.info(f"Found target frame by ID '{self.target_node_id}': '{target_frame.get('name')}'")
            else:
                logger.warning(f"Could not find node '{self.target_node_id}'. Falling back to main frame.")

        if not target_frame:
            target_frame = self._find_main_frame(doc_root)

        if not target_frame:
            # If doc_root is already a frame/component
            if isinstance(doc_root, dict) and doc_root.get("type") in ("FRAME", "COMPONENT", "GROUP"):
                target_frame = doc_root
            else:
                raise ValueError("No suitable Frame found in the Figma file. Please verify the URL or node-id.")

        frame_bbox = target_frame.get("absoluteBoundingBox") or {}
        frame_x = frame_bbox.get("x", 0.0)
        frame_y = frame_bbox.get("y", 0.0)
        frame_w = frame_bbox.get("width", target_frame.get("width", 2000))
        frame_h = frame_bbox.get("height", target_frame.get("height", 2000))

        logger.info(f"Target frame: '{target_frame.get('name')}' (ID: {target_frame.get('id')}) Size: {frame_w}x{frame_h}")

        # Queues for batch asset exports
        elements = []
        svg_export_nodes = []     # List of (node_id, clean_id, filename)
        png_export_nodes = []     # List of (node_id, clean_id, filename)
        image_fill_nodes = []     # List of (node_id, clean_id, filename, image_hash)
        bg_rect_candidate = None  # Full-bleed bottom rectangle candidate

        # 2. Bottom-to-top traversal of frame children
        children = target_frame.get("children", [])

        # Check if the very first child is a full-bleed background rectangle
        if children and len(children) > 0:
            first_child = children[0]
            if first_child.get("type") == "RECTANGLE" and not get_image_fill(first_child):
                c_bbox = first_child.get("absoluteBoundingBox") or {}
                cw = c_bbox.get("width", 0)
                ch = c_bbox.get("height", 0)
                cx = c_bbox.get("x", 0) - frame_x
                cy = c_bbox.get("y", 0) - frame_y
                if abs(cx) < 2 and abs(cy) < 2 and abs(cw - frame_w) < 5 and abs(ch - frame_h) < 5:
                    bg_rect_candidate = first_child

        def traverse_node(node, is_root=False):
            nonlocal bg_rect_candidate

            if not node or not node.get("visible", True):
                return

            if not is_root:
                # Skip the bottom background rectangle so it is not an overlapping editable layer
                if bg_rect_candidate and node.get("id") == bg_rect_candidate.get("id"):
                    return

                bbox = node.get("absoluteBoundingBox") or {}
                node_x = round(bbox.get("x", 0.0) - frame_x, 2) if "x" in bbox else round(float(node.get("x", 0.0)), 2)
                node_y = round(bbox.get("y", 0.0) - frame_y, 2) if "y" in bbox else round(float(node.get("y", 0.0)), 2)
                node_w = round(bbox.get("width", node.get("width", 0.0)), 2)
                node_h = round(bbox.get("height", node.get("height", 0.0)), 2)
                rotation = get_node_rotation(node)
                opacity = round(float(node.get("opacity", 1.0)), 2)
                clean_id = clean_node_id(node.get("id"))
                node_type = node.get("type", "")

                # A. Mask Group: Frame/Group containing child with isMask == True
                if is_mask_group(node):
                    filename = f"masked_group_{clean_id}.png"
                    png_export_nodes.append((node.get("id"), clean_id, filename))
                    elements.append({
                        "id": node.get("id"),
                        "name": node.get("name", "Mask Group"),
                        "type": "IMAGE",
                        "x": node_x,
                        "y": node_y,
                        "width": node_w,
                        "height": node_h,
                        "rotation": rotation,
                        "opacity": opacity,
                        "visible": True,
                        "imageFileName": filename,
                        "src": f"{settings.MEDIA_URL}figma_images/{filename}"
                    })
                    return  # Stop recursion into mask group contents

                # B. System Icon: Name contains a colon (e.g. 'ic:round-business-center')
                if is_icon_node(node):
                    elements.append({
                        "id": node.get("id"),
                        "name": node.get("name"),
                        "type": "ICON",
                        "x": node_x,
                        "y": node_y,
                        "width": node_w,
                        "height": node_h,
                        "rotation": rotation,
                        "opacity": opacity,
                        "visible": True
                    })
                    return

                # C. Text Node: Extract rich typography properties
                if node_type == "TEXT":
                    style = node.get("style", {})
                    font_family = style.get("fontFamily", "Inter")
                    font_size = style.get("fontSize", 16)
                    
                    # Normalize font weight
                    raw_weight = style.get("fontWeight", 400)
                    if isinstance(raw_weight, int):
                        font_weight = FONT_WEIGHT_NAMES.get(raw_weight, "Regular")
                    else:
                        font_weight = str(raw_weight)

                    # Line height
                    line_height = style.get("lineHeightPx")
                    if not line_height and "lineHeightPercentFontSize" in style:
                        line_height = font_size * (style["lineHeightPercentFontSize"] / 100.0)
                    if not line_height:
                        line_height = font_size
                    line_height = round(float(line_height), 2)

                    # Letter spacing
                    letter_spacing = style.get("letterSpacing", 0)
                    try:
                        letter_spacing = round(float(letter_spacing), 2)
                    except (ValueError, TypeError):
                        letter_spacing = 0

                    text_color = solid_fill_to_hex(node.get("fills", []))

                    elements.append({
                        "id": node.get("id"),
                        "name": node.get("name", node.get("characters", "Text")),
                        "type": "TEXT",
                        "x": node_x,
                        "y": node_y,
                        "width": node_w,
                        "height": node_h,
                        "rotation": rotation,
                        "opacity": opacity,
                        "visible": True,
                        "text": node.get("characters", ""),
                        "fontFamily": font_family,
                        "fontSize": font_size,
                        "fontWeight": font_weight,
                        "color": text_color,
                        "textAlign": style.get("textAlignHorizontal", "LEFT"),
                        "lineHeight": line_height,
                        "letterSpacing": letter_spacing
                    })
                    return

                # D. Image Fill Node (raster photo/avatar)
                img_fill = get_image_fill(node)
                if img_fill:
                    image_hash = img_fill.get("imageHash")
                    filename = f"image_{clean_id}.png"
                    if image_hash:
                        image_fill_nodes.append((node.get("id"), clean_id, filename, image_hash))
                    else:
                        png_export_nodes.append((node.get("id"), clean_id, filename))

                    elements.append({
                        "id": node.get("id"),
                        "name": node.get("name", "Image"),
                        "type": "IMAGE",
                        "x": node_x,
                        "y": node_y,
                        "width": node_w,
                        "height": node_h,
                        "rotation": rotation,
                        "opacity": opacity,
                        "visible": True,
                        "imageFileName": filename,
                        "src": f"{settings.MEDIA_URL}figma_images/{filename}",
                        "scaleMode": img_fill.get("scaleMode", "FILL")
                    })
                    return

                # E. Custom Vector Shape
                if node_type in self.CUSTOM_VECTOR_TYPES:
                    filename = f"vector_{clean_id}.svg"
                    svg_export_nodes.append((node.get("id"), clean_id, filename))
                    elements.append({
                        "id": node.get("id"),
                        "name": node.get("name", "Vector"),
                        "type": "IMAGE",
                        "x": node_x,
                        "y": node_y,
                        "width": node_w,
                        "height": node_h,
                        "rotation": rotation,
                        "opacity": opacity,
                        "visible": True,
                        "imageFileName": filename,
                        "src": f"{settings.MEDIA_URL}figma_images/{filename}"
                    })
                    return

                # F. Rectangle Shape (buttons, cards, banners, bars)
                if node_type == "RECTANGLE":
                    filename = f"vector_{clean_id}.svg"
                    svg_export_nodes.append((node.get("id"), clean_id, filename))
                    elements.append({
                        "id": node.get("id"),
                        "name": node.get("name", "Rectangle"),
                        "type": "IMAGE",
                        "x": node_x,
                        "y": node_y,
                        "width": node_w,
                        "height": node_h,
                        "rotation": rotation,
                        "opacity": opacity,
                        "visible": True,
                        "imageFileName": filename,
                        "src": f"{settings.MEDIA_URL}figma_images/{filename}"
                    })
                    return

                # G. Container nodes (FRAME, GROUP, COMPONENT, INSTANCE)
                # If it has children, traverse bottom-to-top
                if "children" in node and node["children"]:
                    for child in node["children"]:
                        traverse_node(child, is_root=False)
                    return
                else:
                    # Leaf container or shape without children: export as SVG if has fills/strokes
                    if node.get("fills") or node.get("strokes"):
                        filename = f"vector_{clean_id}.svg"
                        svg_export_nodes.append((node.get("id"), clean_id, filename))
                        elements.append({
                            "id": node.get("id"),
                            "name": node.get("name", "Shape"),
                            "type": "IMAGE",
                            "x": node_x,
                            "y": node_y,
                            "width": node_w,
                            "height": node_h,
                            "rotation": rotation,
                            "opacity": opacity,
                            "visible": True,
                            "imageFileName": filename,
                            "src": f"{settings.MEDIA_URL}figma_images/{filename}"
                        })
                    return

            # If root frame, traverse all children bottom-to-top
            if "children" in node:
                for child in node["children"]:
                    traverse_node(child, is_root=False)

        # Run bottom-to-top traversal
        traverse_node(target_frame, is_root=True)
        logger.info(f"Traversal complete: found {len(elements)} editable elements "
                    f"({len(svg_export_nodes)} SVGs, {len(png_export_nodes)} PNGs, {len(image_fill_nodes)} Image Fills).")

        # 3. Create destination directory: media/figma_images/
        figma_images_dir = os.path.join(settings.MEDIA_ROOT, "figma_images")
        os.makedirs(figma_images_dir, exist_ok=True)

        # 4. Batch export and download SVGs
        if svg_export_nodes:
            svg_ids = [item[0] for item in svg_export_nodes]
            id_to_filename = {item[0]: item[2] for item in svg_export_nodes}
            try:
                svg_urls = self.figma_service.export_nodes_as_svg(self.file_key, svg_ids)
                for nid, url in svg_urls.items():
                    if url and nid in id_to_filename:
                        dest = os.path.join(figma_images_dir, id_to_filename[nid])
                        try:
                            resp = requests.get(url, timeout=20)
                            if resp.status_code == 200:
                                with open(dest, "wb") as f:
                                    f.write(resp.content)
                                logger.info(f"Downloaded SVG: {id_to_filename[nid]}")
                        except Exception as e:
                            logger.warning(f"Failed to download SVG for node {nid}: {e}")
            except Exception as e:
                logger.error(f"Batch SVG export failed: {e}", exc_info=True)

        # 5. Batch export and download PNGs (masked groups, flattened layers)
        if png_export_nodes:
            png_ids = [item[0] for item in png_export_nodes]
            id_to_filename = {item[0]: item[2] for item in png_export_nodes}
            try:
                png_urls = self.figma_service.export_nodes_as_png(self.file_key, png_ids, scale=1)
                for nid, url in png_urls.items():
                    if url and nid in id_to_filename:
                        dest = os.path.join(figma_images_dir, id_to_filename[nid])
                        try:
                            resp = requests.get(url, timeout=20)
                            if resp.status_code == 200:
                                with open(dest, "wb") as f:
                                    f.write(resp.content)
                                logger.info(f"Downloaded PNG: {id_to_filename[nid]}")
                        except Exception as e:
                            logger.warning(f"Failed to download PNG for node {nid}: {e}")
            except Exception as e:
                logger.error(f"Batch PNG export failed: {e}", exc_info=True)

        # 6. Download image fills from Figma image hash mapping
        if image_fill_nodes:
            try:
                images_map = self.figma_service.get_file_images(self.file_key)
            except Exception as e:
                logger.warning(f"Failed to fetch image mapping: {e}")
                images_map = {}

            missing_image_nodes = []
            for nid, clean_id, filename, img_hash in image_fill_nodes:
                s3_url = images_map.get(img_hash)
                if s3_url:
                    dest = os.path.join(figma_images_dir, filename)
                    try:
                        resp = requests.get(s3_url, timeout=20)
                        if resp.status_code == 200:
                            with open(dest, "wb") as f:
                                f.write(resp.content)
                            logger.info(f"Downloaded image fill: {filename}")
                        else:
                            missing_image_nodes.append(nid)
                    except Exception as e:
                        logger.warning(f"Failed to download image hash {img_hash}: {e}")
                        missing_image_nodes.append(nid)
                else:
                    missing_image_nodes.append(nid)

            # Fallback: export any missing image nodes directly as PNG
            if missing_image_nodes:
                logger.info(f"Falling back to direct PNG export for {len(missing_image_nodes)} image nodes...")
                try:
                    fallback_urls = self.figma_service.export_nodes_as_png(self.file_key, missing_image_nodes, scale=1)
                    for nid, url in fallback_urls.items():
                        if url:
                            clean_id = clean_node_id(nid)
                            dest = os.path.join(figma_images_dir, f"image_{clean_id}.png")
                            resp = requests.get(url, timeout=20)
                            if resp.status_code == 200:
                                with open(dest, "wb") as f:
                                    f.write(resp.content)
                except Exception as e:
                    logger.warning(f"Fallback PNG export failed: {e}")

        # 7. Generate clean background image
        templates_dir = os.path.join(settings.MEDIA_ROOT, "template_backgrounds")
        os.makedirs(templates_dir, exist_ok=True)
        frame_clean_id = clean_node_id(target_frame.get("id"))
        bg_filename = f"{self.file_key}_{frame_clean_id}.png"
        bg_local_path = os.path.join(templates_dir, bg_filename)

        bg_color = None
        bg_image_hash = None

        # Check frame fills
        frame_fills = target_frame.get("fills", [])
        if isinstance(frame_fills, list):
            for fill in frame_fills:
                if isinstance(fill, dict) and fill.get("visible", True):
                    if fill.get("type") == "SOLID":
                        c = fill.get("color", {})
                        opacity = fill.get("opacity", c.get("a", 1.0))
                        bg_color = (
                            int(round(c.get("r", 1) * 255)),
                            int(round(c.get("g", 1) * 255)),
                            int(round(c.get("b", 1) * 255)),
                            int(round(opacity * 255))
                        )
                        break
                    elif fill.get("type") == "IMAGE":
                        bg_image_hash = fill.get("imageHash")
                        break

        # Check backgroundColor
        if not bg_color and not bg_image_hash and "backgroundColor" in target_frame:
            c = target_frame.get("backgroundColor", {})
            bg_color = (
                int(round(c.get("r", 1) * 255)),
                int(round(c.get("g", 1) * 255)),
                int(round(c.get("b", 1) * 255)),
                int(round(c.get("a", 1) * 255))
            )

        # Check background rectangle candidate
        if not bg_color and not bg_image_hash and bg_rect_candidate:
            rect_fills = bg_rect_candidate.get("fills", [])
            for fill in rect_fills:
                if isinstance(fill, dict) and fill.get("visible", True):
                    if fill.get("type") == "SOLID":
                        c = fill.get("color", {})
                        opacity = fill.get("opacity", c.get("a", 1.0))
                        bg_color = (
                            int(round(c.get("r", 1) * 255)),
                            int(round(c.get("g", 1) * 255)),
                            int(round(c.get("b", 1) * 255)),
                            int(round(opacity * 255))
                        )
                        break
                    elif fill.get("type") == "IMAGE":
                        bg_image_hash = fill.get("imageHash")
                        break

        # Generate the background image
        int_w = max(1, int(round(frame_w)))
        int_h = max(1, int(round(frame_h)))

        bg_saved = False
        if bg_image_hash:
            try:
                images_map = self.figma_service.get_file_images(self.file_key)
                s3_url = images_map.get(bg_image_hash)
                if s3_url:
                    resp = requests.get(s3_url, timeout=25)
                    if resp.status_code == 200:
                        with open(bg_local_path, "wb") as f:
                            f.write(resp.content)
                        bg_saved = True
            except Exception as e:
                logger.warning(f"Could not download background image hash {bg_image_hash}: {e}")

        if not bg_saved:
            if not bg_color:
                bg_color = (255, 255, 255, 255)
            pil_img = Image.new("RGBA", (int_w, int_h), bg_color)
            pil_img.save(bg_local_path, format="PNG")
            logger.info(f"Generated clean solid background image: {bg_filename} ({int_w}x{int_h}, color {bg_color})")

        # Copy to media/figma_images/background.png so relative references also resolve
        try:
            figma_bg_dest = os.path.join(figma_images_dir, "background.png")
            shutil.copyfile(bg_local_path, figma_bg_dest)
        except Exception as e:
            logger.warning(f"Could not copy background.png to figma_images: {e}")

        # 8. Assemble template_data
        template_data = {
            "width": int_w,
            "height": int_h,
            "background": "background.png",
            "elements": elements
        }

        return {
            "template_data": template_data,
            "background_image_path": f"template_backgrounds/{bg_filename}",
            "width": int_w,
            "height": int_h
        }