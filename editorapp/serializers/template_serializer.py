from rest_framework import serializers
from ..models import Template

class TemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Template
        fields = [
            'id',
            'name',
            'slug',
            'description',
            'category',
            'thumbnail',
            'template_data',
            'background_image',
            'width',
            'height',
            'figma_url',
            'status',
            'image_1',
            'image_2',
            'image_3',
            'image_4',
            'image_5',
            'image_6',
            'image_7',
            'image_8',
            'image_9',
            'image_10',
            'image_11',
            'image_12',
            'image_13',
            'image_14',
            'image_15',
            'image_16',
            'image_17',
            'image_18',
            'image_19',
            'image_20',
            'session_id',
            'is_user_design',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['slug', 'created_at', 'updated_at']

    def to_representation(self, instance):
        request = self.context.get('request')
        session_id = request.query_params.get('session_id') if request else None
        
        template_data = None
        if session_id:
            try:
                from ..models import TemplateEditSession
                session_edit = TemplateEditSession.objects.get(session_id=session_id, template=instance)
                t_data = session_edit.template_data
                if isinstance(t_data, dict):
                    template_data = dict(t_data)
                elif isinstance(t_data, str) and t_data.strip():
                    import json
                    template_data = json.loads(t_data)
                else:
                    template_data = {}
            except TemplateEditSession.DoesNotExist:
                pass
                
        if template_data is None:
            t_data = instance.template_data
            if isinstance(t_data, dict):
                template_data = dict(t_data)
            elif isinstance(t_data, str) and t_data.strip():
                try:
                    import json
                    template_data = json.loads(t_data)
                except Exception:
                    template_data = {}
            else:
                template_data = {}
            
        data = super().to_representation(instance)
        data['template_data'] = template_data
        
        if template_data and 'elements' in template_data:
            for element in template_data['elements']:
                el_type = (element.get('type') or '').upper()
                if el_type == 'IMAGE' or el_type == 'ICON':
                    el_name = (element.get('name') or '').lower()
                    el_id = element.get('id')
                    
                    matched_field = None
                    import os
                    el_id_normalized = el_id.replace(':', '_') if el_id else ''
                    
                    # 1. Match by normalized element ID inside the DB field filename
                    for i in range(1, 21):
                        image_field = getattr(instance, f"image_{i}", None)
                        if image_field and image_field.name:
                            filename = os.path.basename(image_field.name)
                            if el_id and (el_id in filename or el_id_normalized in filename):
                                matched_field = f"image_{i}"
                                break
                                
                    # 2. Fallback to name-based matching if no match found by filename/ID
                    if not matched_field:
                        for i in range(1, 21):
                            if f"image_{i}" == el_id or f"image {i}" in el_name or f"image_{i}" in el_name:
                                matched_field = f"image_{i}"
                                break
                    
                    if matched_field:
                        image_field = getattr(instance, matched_field, None)
                        if image_field and image_field.name:
                            if request is not None:
                                url = request.build_absolute_uri(image_field.url)
                            else:
                                url = image_field.url
                            
                            # Inject/override with the actual uploaded field URL unless user overridden in session
                            if not element.get('src') or not element.get('src').startswith('/media/user_uploads/'):
                                element['src'] = url
        return data
