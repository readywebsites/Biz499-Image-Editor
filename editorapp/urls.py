from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import TemplateViewSet, ElementViewSet, remove_background_view
from .views.figma_import_viewset import FigmaImportJobViewSet
from .views.image_view import serve_image, serve_icon, upload_image_view
from .views.magic_erase_view import magic_erase_view
from .views.diagnostics_view import system_diagnostics_view

router = DefaultRouter()
router.register(r'templates', TemplateViewSet, basename='template')
router.register(r'import-jobs', FigmaImportJobViewSet, basename='import-job')
router.register(r'elements', ElementViewSet, basename='element')

urlpatterns = [
    path('system-diagnostics/', system_diagnostics_view, name='system-diagnostics'),
    path('image/<str:image_hash>/', serve_image, name='serve-image'),
    path('icon/<str:provider>/<str:name>.svg', serve_icon, name='serve-icon'),
    path('upload-image/', upload_image_view, name='upload-image'),
    path('magic-erase/', magic_erase_view, name='magic-erase'),
    path('remove-background/', remove_background_view, name='remove-background'),
    path('', include(router.urls)),
]

