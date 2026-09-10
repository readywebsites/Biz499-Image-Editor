from rest_framework import viewsets
from ..models import FigmaImportJob
from ..serializers.figma_import_serializer import FigmaImportJobSerializer
from ..services.figma_runner import start_figma_import_background

class FigmaImportJobViewSet(viewsets.ModelViewSet):
    queryset = FigmaImportJob.objects.all().order_by('-created_at')
    serializer_class = FigmaImportJobSerializer

    def perform_create(self, serializer):
        # Save job as pending
        job = serializer.save(status='pending')
        
        # Trigger unified background processing runner
        start_figma_import_background(job.id)
