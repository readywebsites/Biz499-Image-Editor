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

def get_svg_dimensions(svg_path):
    """Extracts width and height from an SVG file's attributes or viewBox."""
    try:
        import xml.etree.ElementTree as ET
        tree = ET.parse(svg_path)
        root = tree.getroot()
        w = root.get('width')
        h = root.get('height')
        viewbox = root.get('viewBox')
        if w and h:
            w_val = float(re.sub(r'[^\d.]', '', w))
            h_val = float(re.sub(r'[^\d.]', '', h))
            return w_val, h_val
        elif viewbox:
            parts = [float(p) for p in viewbox.split()]
            if len(parts) == 4:
                return parts[2], parts[3]
    except Exception as e:
        logger.warning(f"Failed to parse SVG dimensions from {svg_path}: {e}")
    return None, None

def has_text_nodes(node):
    """Recursively checks if a node or any of its descendants is a TEXT node."""
    if not isinstance(node, dict):
        return False
    if node.get("type") == "TEXT":
        return True
    for child in node.get("children", []):
        if has_text_nodes(child):
            return True
    return False

def is_mask_group(node):
    """
    Checks if a group or frame is a legitimate visual mask group (e.g. a masked photo,
    avatar, or shape clip) that should be exported as a single raster PNG.
    
    CRITICAL: Never treat containers with TEXT layers or high-level layout frames as mask groups!
    """
    if not isinstance(node, dict):
        return False

    # Never treat frames/groups containing text layers as mask groups!
    if has_text_nodes(node):
        return False

    name = (node.get("name") or "").strip().lower()
    node_type = node.get("type", "")

    # Top-level page elements should never be treated as mask groups
    if node_type in ("CANVAS", "DOCUMENT", "SECTION"):
        return False

    # Explicitly named mask group
    if "mask group" in name or "clip path group" in name or "mask_group" in name or name == "mask":
        return True

    # Real mask group in Figma: must have an actual child where isMask == True or is named mask
    children = node.get("children", [])
    if node_type in ("FRAME", "GROUP", "COMPONENT", "INSTANCE", "BOOLEAN_OPERATION"):
        if children and len(children) <= 20:
            has_mask_child = any(c.get("isMask") is True or "mask" in (c.get("name") or "").lower() for c in children)
            if has_mask_child:
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

def find_icon_color(node):
    """Recursively extracts the first non-transparent solid fill or stroke color from an icon node tree."""
    def _extract_color(fills):
        if fills and isinstance(fills, list):
            for fill in fills:
                if isinstance(fill, dict) and fill.get("visible", True) and fill.get("type") == "SOLID":
                    color = fill.get("color", {})
                    opacity = fill.get("opacity", 1.0)
                    if opacity > 0:
                        r = int(round(color.get("r", 0) * 255))
                        g = int(round(color.get("g", 0) * 255))
                        b = int(round(color.get("b", 0) * 255))
                        return f"#{r:02x}{g:02x}{b:02x}"
        return None

    # First check node's own fills/strokes
    c = _extract_color(node.get("fills"))
    if c:
        return c
    c = _extract_color(node.get("strokes"))
    if c:
        return c

    # Recursively search all descendant children
    def _search_children(n):
        for child in n.get("children", []):
            if not child.get("visible", True):
                continue
            c_fill = _extract_color(child.get("fills"))
            if c_fill:
                return c_fill
            c_stroke = _extract_color(child.get("strokes"))
            if c_stroke:
                return c_stroke
            res = _search_children(child)
            if res:
                return res
        return None

    c = _search_children(node)
    if c:
        return c

    name_lower = (node.get("name") or "").lower()
    if "white" in name_lower or "business-center" in name_lower:
        return "#ffffff"
    if "phone" in name_lower:
        return "#007c7c"
    return "#000000"

def has_visible_fill(node):
    """Checks if a node has any visible fills."""
    fills = node.get("fills")
    if isinstance(fills, list):
        for f in fills:
            if isinstance(f, dict) and f.get("visible", True) and f.get("opacity", 1.0) > 0:
                return True
    return False

def has_visible_stroke(node):
    """Checks if a node has any visible strokes."""
    strokes = node.get("strokes")
    if isinstance(strokes, list):
        for s in strokes:
            if isinstance(s, dict) and s.get("visible", True) and s.get("opacity", 1.0) > 0:
                return True
    return False

def generate_container_svg(width, height, fills=None, strokes=None, stroke_weight=1, corner_radius=0, corner_radii=None):
    """
    Generates a clean SVG string for a container's background shape (rectangle/pill/card),
    preserving exact corner radii, solid/gradient fills, and strokes without rendering child text.
    """
    w = max(1.0, float(width))
    h = max(1.0, float(height))
    
    fill_attr = 'fill="none"'
    defs = []
    
    if fills and isinstance(fills, list):
        for fill in fills:
            if not isinstance(fill, dict) or not fill.get("visible", True):
                continue
            fill_type = fill.get("type", "SOLID")
            opacity = fill.get("opacity", 1.0)
            
            if fill_type == "SOLID":
                c = fill.get("color", {})
                r = int(round(c.get("r", 1) * 255))
                g = int(round(c.get("g", 1) * 255))
                b = int(round(c.get("b", 1) * 255))
                hex_color = f"#{r:02x}{g:02x}{b:02x}"
                if opacity < 0.999:
                    fill_attr = f'fill="{hex_color}" fill-opacity="{opacity:.3f}"'
                else:
                    fill_attr = f'fill="{hex_color}"'
                break
            elif fill_type == "GRADIENT_LINEAR":
                grad_id = f"grad_{abs(hash(str(fill)))}"
                handles = fill.get("gradientHandlePositions", [{"x": 0, "y": 0}, {"x": 1, "y": 0}])
                x1 = handles[0].get("x", 0) * 100
                y1 = handles[0].get("y", 0) * 100
                x2 = handles[1].get("x", 1) * 100
                y2 = handles[1].get("y", 0) * 100
                stops_xml = []
                for stop in fill.get("gradientStops", []):
                    sc = stop.get("color", {})
                    sr = int(round(sc.get("r", 0) * 255))
                    sg = int(round(sc.get("g", 0) * 255))
                    sb = int(round(sc.get("b", 0) * 255))
                    sa = sc.get("a", 1.0)
                    pos = stop.get("position", 0) * 100
                    stops_xml.append(f'<stop offset="{pos:.1f}%" stop-color="#{sr:02x}{sg:02x}{sb:02x}" stop-opacity="{sa:.3f}"/>')
                defs.append(f'<linearGradient id="{grad_id}" x1="{x1:.1f}%" y1="{y1:.1f}%" x2="{x2:.1f}%" y2="{y2:.1f}%">{"".join(stops_xml)}</linearGradient>')
                fill_attr = f'fill="url(#{grad_id})"'
                break

    stroke_attr = ''
    if strokes and isinstance(strokes, list):
        for stroke in strokes:
            if not isinstance(stroke, dict) or not stroke.get("visible", True):
                continue
            if stroke.get("type") == "SOLID":
                c = stroke.get("color", {})
                r = int(round(c.get("r", 0) * 255))
                g = int(round(c.get("g", 0) * 255))
                b = int(round(c.get("b", 0) * 255))
                hex_color = f"#{r:02x}{g:02x}{b:02x}"
                s_op = stroke.get("opacity", 1.0)
                sw = max(0.5, float(stroke_weight or 1))
                if s_op < 0.999:
                    stroke_attr = f' stroke="{hex_color}" stroke-width="{sw}" stroke-opacity="{s_op:.3f}"'
                else:
                    stroke_attr = f' stroke="{hex_color}" stroke-width="{sw}"'
                break

    defs_xml = f"<defs>{''.join(defs)}</defs>" if defs else ""

    if corner_radii and len(corner_radii) == 4 and any(r > 0 for r in corner_radii):
        tl, tr, br, bl = corner_radii
        path_d = (
            f"M {tl} 0 "
            f"H {w - tr} "
            f"A {tr} {tr} 0 0 1 {w} {tr} "
            f"V {h - br} "
            f"A {br} {br} 0 0 1 {w - br} {h} "
            f"H {bl} "
            f"A {bl} {bl} 0 0 1 0 {h - bl} "
            f"V {tl} "
            f"A {tl} {tl} 0 0 1 {tl} 0 Z"
        )
        shape_xml = f'<path d="{path_d}" {fill_attr}{stroke_attr}/>'
    elif corner_radius and corner_radius > 0:
        cr = min(corner_radius, min(w, h) / 2)
        shape_xml = f'<rect width="{w}" height="{h}" rx="{cr}" ry="{cr}" {fill_attr}{stroke_attr}/>'
    else:
        shape_xml = f'<rect width="{w}" height="{h}" {fill_attr}{stroke_attr}/>'

    return f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" fill="none" xmlns="http://www.w3.org/2000/svg">{defs_xml}{shape_xml}</svg>'

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
        'VECTOR', 'BOOLEAN_OPERATION', 'BOOLEAN', 'STAR', 'LINE',
        'ELLIPSE', 'POLYGON', 'REGULAR_POLYGON', 'SHAPE_WITH_TEXT',
        'STAMP', 'HIGHLIGHT', 'WASHI_TAPE'
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
        """Finds the main FRAME or COMPONENT in the document or canvas."""
        if not start_node or not isinstance(start_node, dict):
            return None
        if start_node.get("type") in ("FRAME", "COMPONENT"):
            return start_node

        candidates = []
        def _search(n):
            if not n or not isinstance(n, dict):
                return
            ntype = n.get("type")
            if ntype in ("FRAME", "COMPONENT"):
                candidates.append(n)
                return  # Do not recurse inside a candidate frame
            for c in n.get("children", []):
                _search(c)

        _search(start_node)

        if candidates:
            # Sort by area (largest frame is the primary design canvas)
            def frame_area(f):
                bbox = f.get("absoluteBoundingBox") or f.get("absoluteRenderBounds") or {}
                return float(bbox.get("width", 0)) * float(bbox.get("height", 0))
            candidates.sort(key=frame_area, reverse=True)
            return candidates[0]

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
                logger.info(f"Found target node by ID '{self.target_node_id}': '{target_frame.get('name')}' ({target_frame.get('type')})")
            else:
                logger.warning(f"Could not find node '{self.target_node_id}'. Falling back to main frame.")

        # If target_frame is a CANVAS, DOCUMENT, or SECTION, resolve to the actual design FRAME inside
        if target_frame and target_frame.get("type") in ("CANVAS", "DOCUMENT", "SECTION"):
            resolved = self._find_main_frame(target_frame)
            if resolved:
                logger.info(f"Target node '{target_frame.get('id')}' was a {target_frame.get('type')}. Resolved to inner FRAME '{resolved.get('name')}' (ID: {resolved.get('id')}).")
                target_frame = resolved

        if not target_frame:
            target_frame = self._find_main_frame(doc_root)

        if not target_frame:
            # If doc_root is already a frame/component
            if isinstance(doc_root, dict) and doc_root.get("type") in ("FRAME", "COMPONENT", "GROUP"):
                target_frame = doc_root
            else:
                raise ValueError("No suitable Frame found in the Figma file. Please verify the URL or node-id.")

        # Ensure target_frame has valid bounding box and is not a canvas
        if target_frame.get("type") in ("CANVAS", "DOCUMENT", "SECTION"):
            resolved = self._find_main_frame(target_frame)
            if resolved:
                target_frame = resolved

        frame_bbox = target_frame.get("absoluteBoundingBox") or target_frame.get("absoluteRenderBounds") or {}
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
        generated_svg_files = {}  # Map of filename -> svg_string
        bg_rect_candidate = None  # Full-bleed bottom rectangle candidate

        # 2. Bottom-to-top traversal of frame children
        children = target_frame.get("children", [])

        # Check if the very first child is a full-bleed background rectangle
        if children and len(children) > 0:
            first_child = children[0]
            if first_child.get("type") == "RECTANGLE" and not get_image_fill(first_child):
                c_bbox = first_child.get("absoluteBoundingBox") or first_child.get("absoluteRenderBounds") or {}
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
                bbox = node.get("absoluteBoundingBox") or node.get("absoluteRenderBounds") or {}
                if "x" in bbox:
                    node_x = round(bbox.get("x", 0.0) - frame_x, 2)
                    node_y = round(bbox.get("y", 0.0) - frame_y, 2)
                else:
                    abs_transform = node.get("absoluteTransform")
                    if abs_transform and len(abs_transform) >= 2 and len(abs_transform[0]) >= 3:
                        node_x = round(float(abs_transform[0][2]) - frame_x, 2)
                        node_y = round(float(abs_transform[1][2]) - frame_y, 2)
                    else:
                        node_x = round(float(node.get("x", 0.0)), 2)
                        node_y = round(float(node.get("y", 0.0)), 2)

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

                    # For a mask group, the visible bounds are defined by the mask layer
                    mask_child = None
                    for c in node.get("children", []):
                        if c.get("isMask") or "mask" in (c.get("name") or "").lower():
                            mask_child = c
                            break
                    if not mask_child and node.get("children"):
                        mask_child = node["children"][0]

                    m_bbox = mask_child.get("absoluteBoundingBox") or mask_child.get("absoluteRenderBounds") or bbox
                    m_x = round(m_bbox.get("x", bbox.get("x", 0.0)) - frame_x, 2)
                    m_y = round(m_bbox.get("y", bbox.get("y", 0.0)) - frame_y, 2)
                    m_w = round(m_bbox.get("width", node_w), 2)
                    m_h = round(m_bbox.get("height", node_h), 2)

                    elements.append({
                        "id": node.get("id"),
                        "name": node.get("name", "Mask Group"),
                        "type": "IMAGE",
                        "x": m_x,
                        "y": m_y,
                        "width": m_w,
                        "height": m_h,
                        "rotation": rotation,
                        "opacity": opacity,
                        "visible": True,
                        "imageFileName": filename,
                        "src": f"{settings.MEDIA_URL}figma_images/{filename}",
                        "_is_mask_group": True
                    })
                    return  # Stop recursion into mask group contents

                # B. System Icon: Name contains a colon (e.g. 'ic:round-business-center')
                if is_icon_node(node):
                    icon_color = find_icon_color(node)
                    parts = node.get("name", "").split(":")
                    icon_src = f"/api/icon/{parts[0]}/{parts[1]}.svg?color={icon_color.replace('#', '%23')}"

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
                        "visible": True,
                        "color": icon_color,
                        "src": icon_src
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
                        "content": node.get("characters", ""),
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

                    img_el = {
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
                    }
                    if node_type == "ELLIPSE":
                        img_el["cornerRadius"] = round(max(node_w, node_h) / 2, 2)
                    elements.append(img_el)

                    # If container has children on top of image fill, traverse them
                    if "children" in node and node["children"]:
                        for child in node["children"]:
                            traverse_node(child, is_root=False)
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
                if "children" in node and node["children"]:
                    # If the container itself has visible fills or strokes (e.g. Button pill, Card, Badge),
                    # emit its background shape first so it is preserved and sits beneath its child text/icons
                    if node_type in ("FRAME", "COMPONENT", "INSTANCE") and (has_visible_fill(node) or has_visible_stroke(node)):
                        cr = float(node.get("cornerRadius", 0))
                        cr_list = node.get("rectangleCornerRadii")
                        bg_svg_content = generate_container_svg(
                            width=node_w,
                            height=node_h,
                            fills=node.get("fills"),
                            strokes=node.get("strokes"),
                            stroke_weight=node.get("strokeWeight", 1),
                            corner_radius=cr,
                            corner_radii=cr_list
                        )
                        bg_filename = f"vector_{clean_id}_bg.svg"
                        generated_svg_files[bg_filename] = bg_svg_content
                        elements.append({
                            "id": f"{node.get('id')}_bg",
                            "name": f"{node.get('name', 'Container')} Background",
                            "type": "IMAGE",
                            "x": node_x,
                            "y": node_y,
                            "width": node_w,
                            "height": node_h,
                            "rotation": rotation,
                            "opacity": opacity,
                            "visible": True,
                            "imageFileName": bg_filename,
                            "src": f"{settings.MEDIA_URL}figma_images/{bg_filename}"
                        })

                    # Traverse children bottom-to-top so they sit on top of the container's background
                    for child in node["children"]:
                        traverse_node(child, is_root=False)
                    return
                else:
                    # Leaf container or shape without children (leaf FRAME, COMPONENT, INSTANCE, or Shape):
                    # Export as SVG so leaf icons, illustrations, and shapes are never dropped
                    if node.get("fills") or node.get("strokes") or node_type in ("COMPONENT", "INSTANCE", "FRAME"):
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
                    f"({len(svg_export_nodes)} SVGs, {len(png_export_nodes)} PNGs, {len(image_fill_nodes)} Image Fills, {len(generated_svg_files)} Generated SVGs).")

        # 3. Create destination directory: media/figma_images/
        figma_images_dir = os.path.join(settings.MEDIA_ROOT, "figma_images")
        os.makedirs(figma_images_dir, exist_ok=True)

        # Write any dynamically generated container background SVGs
        for gen_filename, gen_content in generated_svg_files.items():
            try:
                dest = os.path.join(figma_images_dir, gen_filename)
                with open(dest, "w", encoding="utf-8") as f:
                    f.write(gen_content)
                logger.info(f"Saved generated container SVG: {gen_filename}")
            except Exception as e:
                logger.warning(f"Failed to write generated SVG {gen_filename}: {e}")

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

            # Adjust vector element bounds according to downloaded SVG viewBox / frame intersection
            for el in elements:
                if el.get("type") == "IMAGE" and el.get("imageFileName", "").endswith(".svg"):
                    svg_dest = os.path.join(figma_images_dir, el["imageFileName"])
                    if os.path.exists(svg_dest):
                        svg_w, svg_h = get_svg_dimensions(svg_dest)
                        if svg_w and svg_h:
                            inter_x = max(0.0, el["x"])
                            inter_y = max(0.0, el["y"])
                            inter_w = max(0.0, min(float(frame_w), el["x"] + el["width"]) - inter_x)
                            inter_h = max(0.0, min(float(frame_h), el["y"] + el["height"]) - inter_y)

                            if abs(svg_w - inter_w) < 2 and abs(svg_h - inter_h) < 2:
                                el["x"] = round(inter_x, 2)
                                el["y"] = round(inter_y, 2)
                            elif abs(svg_w - inter_w) < 2:
                                el["x"] = round(inter_x, 2)
                            elif abs(svg_h - inter_h) < 2:
                                el["y"] = round(inter_y, 2)
                            else:
                                if el["x"] < 0 and abs(svg_w - frame_w) < 2:
                                    el["x"] = 0.0
                                if el["y"] < 0 and abs(svg_h - frame_h) < 2:
                                    el["y"] = 0.0
                            el["width"] = round(svg_w, 2)
                            el["height"] = round(svg_h, 2)

        # 5. Batch export and download PNGs (masked groups, flattened layers)
        if png_export_nodes:
            png_ids = [item[0] for item in png_export_nodes]
            id_to_filename = {item[0]: item[2] for item in png_export_nodes}
            try:
                png_urls = self.figma_service.export_nodes_as_png(self.file_key, png_ids, scale=1, use_absolute_bounds=False)
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

            # Adjust raster and masked group bounds according to downloaded PNG dimensions
            for el in elements:
                if el.get("type") == "IMAGE" and el.get("imageFileName", "").endswith(".png"):
                    png_dest = os.path.join(figma_images_dir, el["imageFileName"])
                    if os.path.exists(png_dest):
                        try:
                            with Image.open(png_dest) as img:
                                png_w, png_h = img.size
                            is_mask = el.pop("_is_mask_group", False)
                            inter_x = max(0.0, el["x"])
                            inter_y = max(0.0, el["y"])
                            inter_w = max(0.0, min(float(frame_w), el["x"] + el["width"]) - inter_x)
                            inter_h = max(0.0, min(float(frame_h), el["y"] + el["height"]) - inter_y)

                            if is_mask:
                                if abs(png_w - inter_w) < 2 and abs(png_h - inter_h) < 2:
                                    el["x"] = round(inter_x, 2)
                                    el["y"] = round(inter_y, 2)
                                elif abs(png_h - inter_h) < 2 and el["y"] < 0:
                                    el["y"] = round(inter_y, 2)
                                elif abs(png_w - inter_w) < 2 and el["x"] < 0:
                                    el["x"] = round(inter_x, 2)
                                elif el["x"] < 0 and abs(png_w - frame_w) < 2:
                                    el["x"] = 0.0
                                if el["y"] < 0 and abs(png_h - frame_h) < 2:
                                    el["y"] = 0.0
                            else:
                                if el["x"] < 0 and abs(png_w - frame_w) < 2:
                                    el["x"] = 0.0
                                if el["y"] < 0 and abs(png_h - frame_h) < 2:
                                    el["y"] = 0.0

                            el["width"] = round(float(png_w), 2)
                            el["height"] = round(float(png_h), 2)
                        except Exception as e:
                            logger.warning(f"Could not read PNG dimensions from {png_dest}: {e}")

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

        # Pop any remaining internal temporary flags
        for el in elements:
            el.pop("_is_mask_group", None)

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