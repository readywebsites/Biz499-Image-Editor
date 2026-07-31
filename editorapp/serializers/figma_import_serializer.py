from rest_framework import serializers
from ..models import FigmaImportJob

class FigmaImportJobSerializer(serializers.ModelSerializer):
    template_slug = serializers.CharField(source='template.slug', read_only=True, allow_null=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = FigmaImportJob
        fields = [
            'id', 'name', 'figma_url', 'status', 'status_display', 
            'error_message', 'template', 'template_slug', 'created_at', 'updated_at'
        ]
        read_only_fields = ['status', 'error_message', 'template', 'created_at', 'updated_at']