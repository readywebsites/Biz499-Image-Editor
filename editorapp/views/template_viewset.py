from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from ..models import Template, TemplateEditSession
from ..serializers import TemplateSerializer

class TemplateViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows templates to be viewed or edited.
    """
    queryset = Template.objects.all().order_by('-created_at')
    serializer_class = TemplateSerializer
    lookup_field = 'slug'

    def get_queryset(self):
        queryset = Template.objects.all()
        session_id = self.request.query_params.get('session_id')
        is_user_design = self.request.query_params.get('is_user_design')
        
        # Detail actions (retrieve, update, partial_update) can access both public templates 
        # and designs belonging to the current session.
        if self.action in ['retrieve', 'update', 'partial_update']:
            if session_id:
                from django.db.models import Q
                return queryset.filter(Q(is_user_design=False) | Q(session_id=session_id, is_user_design=True)).order_by('-created_at')
            return queryset.filter(is_user_design=False).order_by('-created_at')
            
        # List actions
        if is_user_design == 'true':
            if session_id:
                queryset = queryset.filter(session_id=session_id, is_user_design=True)
            else:
                queryset = queryset.none()
        else:
            # Default to public explorer templates
            queryset = queryset.filter(is_user_design=False)
            
        return queryset.order_by('-created_at')

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        session_id = request.query_params.get('session_id')
        if session_id and isinstance(response.data, list):
            edit_sessions = {
                se.template_id: se.template_data
                for se in TemplateEditSession.objects.filter(session_id=session_id)
            }
            if edit_sessions:
                for item in response.data:
                    template_id = item.get('id')
                    if template_id in edit_sessions:
                        item['template_data'] = edit_sessions[template_id]
        return response

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        session_id = request.query_params.get('session_id')
        
        serializer = self.get_serializer(instance)
        data = serializer.data
        
        if session_id:
            try:
                session_edit = TemplateEditSession.objects.get(
                    session_id=session_id,
                    template=instance
                )
                data['template_data'] = session_edit.template_data
            except TemplateEditSession.DoesNotExist:
                pass
                
        return Response(data)

    def update(self, request, *args, **kwargs):
        session_id = request.query_params.get('session_id')
        if not session_id:
            # Fall back to standard update when no session_id is provided (e.g. admin panel)
            return super().update(request, *args, **kwargs)
            
        instance = self.get_object()
        template_data = request.data.get('template_data')
        
        if template_data is None:
            return Response({"error": "template_data is required"}, status=status.HTTP_400_BAD_REQUEST)
            
        session_edit, created = TemplateEditSession.objects.get_or_create(
            session_id=session_id,
            template=instance
        )
        session_edit.template_data = template_data
        session_edit.save()

        # Always persist template_data directly on the template object as well
        instance.template_data = template_data
        instance.save()
        
        # Return base template details but with session-specific template_data
        serializer = self.get_serializer(instance)
        data = serializer.data
        data['template_data'] = template_data
        
        return Response(data)

    @action(detail=True, methods=['post'], url_path='use-template')
    def use_template(self, request, slug=None):
        session_id = request.data.get('session_id')
        if not session_id:
            return Response({"error": "session_id is required"}, status=status.HTTP_400_BAD_REQUEST)
            
        instance = self.get_object()
        
        # Duplicate the template instance for user design
        new_design = Template.objects.create(
            name=f"{instance.name} (Copy)",
            description=instance.description,
            category=instance.category,
            thumbnail=instance.thumbnail,
            template_data=instance.template_data,
            width=instance.width,
            height=instance.height,
            background_image=instance.background_image,
            session_id=session_id,
            is_user_design=True,
            status='published',
            image_1=instance.image_1,
            image_2=instance.image_2,
            image_3=instance.image_3,
            image_4=instance.image_4,
            image_5=instance.image_5,
            image_6=instance.image_6,
            image_7=instance.image_7,
            image_8=instance.image_8,
            image_9=instance.image_9,
            image_10=instance.image_10,
            image_11=instance.image_11,
            image_12=instance.image_12,
            image_13=instance.image_13,
            image_14=instance.image_14,
            image_15=instance.image_15,
            image_16=instance.image_16,
            image_17=instance.image_17,
            image_18=instance.image_18,
            image_19=instance.image_19,
            image_20=instance.image_20,
        )
        
        serializer = self.get_serializer(new_design)
        return Response(serializer.data, status=status.HTTP_201_CREATED)