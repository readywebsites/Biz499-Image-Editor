from rest_framework import serializers
from ..models import Element

class ElementSerializer(serializers.ModelSerializer):
    class Meta:
        model = Element
        fields = [
            'id',
            'name',
            'element_type',
            'category',
            'src',
            'svg_content',
            'file',
            'width',
            'height',
            'data_json',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
