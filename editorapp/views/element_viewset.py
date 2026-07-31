from rest_framework import viewsets, status
from rest_framework.response import Response
from ..models import Element, Template
from ..serializers import ElementSerializer

class ElementViewSet(viewsets.ModelViewSet):
    """
    API endpoint to list and create reusable design elements (SVGs, Shapes, Icons, Images).
    Automatically populates the Element database model with all unique elements extracted from templates,
    allowing administrators to view, modify, or add more elements easily.
    """
    queryset = Element.objects.all().order_by('-created_at')
    serializer_class = ElementSerializer

    def extract_template_elements(self):
        """Extracts unique design elements, SVGs, icons, and shapes from all Template models."""
        extracted_elements = []
        existing_keys = set()
        templates = Template.objects.all()

        def extract_nodes(nodes, tname):
            if not nodes:
                return
            node_list = nodes if isinstance(nodes, list) else [nodes]
            for node in node_list:
                if not isinstance(node, dict):
                    continue
                
                ntype = str(node.get('type', '')).upper()
                name = node.get('name') or ''
                src = node.get('src') or ''
                
                is_element = (
                    ntype in ['VECTOR', 'STAR', 'REGULAR_POLYGON', 'BOOLEAN_OPERATION', 'LINE', 'ICON', 'ELLIPSE', 'RECTANGLE', 'IMAGE']
                    or (src and ('.svg' in src or '.png' in src or '.jpg' in src or '/media/' in src or 'http' in src))
                    or (':' in name)
                )

                if is_element and (src or ':' in name or ntype in ['ELLIPSE', 'RECTANGLE', 'VECTOR', 'STAR']):
                    lookup_key = src if src else f"{name}_{ntype}"
                    if lookup_key and lookup_key not in existing_keys:
                        existing_keys.add(lookup_key)
                        
                        category = 'Vector Shapes'
                        if ':' in name or ntype == 'ICON':
                            category = 'Icons'
                        elif 'Ellipse' in name or 'Circle' in name or ntype == 'ELLIPSE':
                            category = 'Badges & Circles'
                        elif ntype == 'IMAGE' or '.png' in src or '.jpg' in src:
                            category = 'Images & Graphics'
                        elif 'Vector' in name or 'Subtract' in name or 'Union' in name or ntype in ['VECTOR', 'STAR', 'LINE']:
                            category = 'Design Accents'

                        element_item = {
                            'id': f"tpl_el_{len(extracted_elements) + 1000}",
                            'name': name or f"{ntype.capitalize()} Element",
                            'element_type': 'icon' if (':' in name or ntype == 'ICON') else ('image' if ntype == 'IMAGE' else 'svg'),
                            'category': category,
                            'src': src,
                            'width': float(node.get('width') or 100),
                            'height': float(node.get('height') or 100),
                            'data_json': node
                        }
                        extracted_elements.append(element_item)

                if 'children' in node and isinstance(node['children'], list):
                    extract_nodes(node['children'], tname)

        for t in templates:
            tdata = t.template_data
            if tdata and isinstance(tdata, dict):
                children = tdata.get('children') or tdata.get('elements') or []
                extract_nodes(children, t.name)

        return extracted_elements

    def sync_template_svgs_to_db(self, extracted):
        """Persists extracted elements into the Element database table."""
        try:
            existing_srcs = set(Element.objects.values_list('src', flat=True))
            existing_names = set(Element.objects.values_list('name', flat=True))
            
            elements_to_create = []
            for item in extracted:
                lookup_key = item['src'] if item['src'] else item['name']
                if lookup_key not in existing_srcs and item['name'] not in existing_names:
                    existing_srcs.add(lookup_key)
                    existing_names.add(item['name'])
                    
                    el_obj = Element(
                        name=item['name'],
                        element_type=item['element_type'],
                        category=item['category'],
                        src=item['src'],
                        width=item['width'],
                        height=item['height'],
                        data_json=item['data_json']
                    )
                    elements_to_create.append(el_obj)

            if elements_to_create:
                Element.objects.bulk_create(elements_to_create, ignore_conflicts=True)
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Auto-sync template elements to Element DB failed: {e}")

    def list(self, request, *args, **kwargs):
        extracted = self.extract_template_elements()

        # Try syncing and reading from DB table
        try:
            self.sync_template_svgs_to_db(extracted)
            db_elements = Element.objects.all().order_by('category', '-created_at')
            serializer = self.get_serializer(db_elements, many=True)
            results = list(serializer.data)
            if len(results) > 0:
                return Response(results, status=status.HTTP_200_OK)
        except Exception as e:
            pass

        # Fallback to extracted template elements if migration is pending or table empty
        return Response(extracted, status=status.HTTP_200_OK)
