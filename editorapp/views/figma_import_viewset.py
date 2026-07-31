import os
import subprocess
from django.conf import settings
from rest_framework import viewsets
from ..models import FigmaImportJob
from ..serializers.figma_import_serializer import FigmaImportJobSerializer

class FigmaImportJobViewSet(viewsets.ModelViewSet):
    queryset = FigmaImportJob.objects.all().order_by('-created_at')
    serializer_class = FigmaImportJobSerializer

    def perform_create(self, serializer):
        # Save job as pending
        job = serializer.save(status='pending')
        
        # Trigger background processing command
        try:
            python_executable = os.path.join(settings.BASE_DIR, 'env', 'Scripts', 'python.exe')
            manage_py_path = os.path.join(settings.BASE_DIR, 'manage.py')
            
            if os.path.exists(python_executable):
                command = [python_executable, manage_py_path, 'process_figma_imports']
                subprocess.Popen(command, cwd=settings.BASE_DIR)
        except Exception:
            pass
