import logging
import subprocess
import os
from django.conf import settings
from django.contrib import admin, messages
from django.urls import reverse
from django.utils.html import format_html
from django.http import HttpResponseRedirect
from .models import Template, FigmaImportJob, Element

logger = logging.getLogger(__name__)

@admin.register(Element)
class ElementAdmin(admin.ModelAdmin):
    list_display = ('name', 'element_type', 'category', 'created_at')
    list_filter = ('element_type', 'category')
    search_fields = ('name', 'category', 'src')

@admin.register(Template)
class TemplateAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'status', 'created_at', 'updated_at')
    list_filter = ('status', 'category')
    search_fields = ('name', 'description')
    prepopulated_fields = {'slug': ('name',)}
    date_hierarchy = 'created_at'
    ordering = ('status', '-created_at')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        (None, {
            'fields': ('name', 'slug', 'description', 'category', 'status', 'figma_url')
        }),
        ('Template Data (Populated automatically or entered manually)', {
            'fields': ('template_data', 'background_image', 'width', 'height')
        }),
        ('Admin Uploadable Editable Images', {
            'fields': (
                'image_1', 'image_2', 'image_3', 'image_4', 'image_5',
                'image_6', 'image_7', 'image_8', 'image_9', 'image_10',
                'image_11', 'image_12', 'image_13', 'image_14', 'image_15',
                'image_16', 'image_17', 'image_18', 'image_19', 'image_20'
            )
        }),
        ('Read-only', {
            'classes': ('collapse',),
            'fields': ('created_at', 'updated_at', 'thumbnail')
        })
    )

@admin.register(FigmaImportJob)
class FigmaImportJobAdmin(admin.ModelAdmin):
    list_display = ('name', 'status', 'created_at', 'template')
    list_filter = ('status',)
    readonly_fields = ('status', 'error_message', 'template', 'created_at', 'updated_at')
    search_fields = ('name', 'figma_url')
    ordering = ('-created_at',)

    fieldsets = (
        (None, {
            'fields': ('name', 'figma_url')
        }),
        ('Job Status', {
            'classes': ('collapse',),
            'fields': readonly_fields,
        }),
    )

    def save_model(self, request, obj, form, change):
        # If resaving an existing job, reset status to run it again.
        if change:
            obj.status = 'pending'
            obj.template = None
            obj.error_message = None
        
        super().save_model(request, obj, form, change)

        try:
            # Correctly locate the python executable in the virtualenv
            # On Windows, it's in 'env/Scripts/python.exe'
            python_executable = os.path.join(settings.BASE_DIR, 'env', 'Scripts', 'python.exe')
            manage_py_path = os.path.join(settings.BASE_DIR, 'manage.py')

            if not os.path.exists(python_executable):
                 raise FileNotFoundError(f"Python executable not found at {python_executable}")

            # Command to execute
            command = [python_executable, manage_py_path, 'process_figma_imports']

            # Use Popen to run the command in a new process without blocking.
            # cwd is set to the backend directory where manage.py is.
            subprocess.Popen(command, cwd=settings.BASE_DIR)
            
            messages.info(request, "The Figma import job has been started in the background. You can refresh this page to see its status.")

        except FileNotFoundError as e:
            error_msg = f"Could not start background process: {e}. Please run the import manually via the command line."
            messages.error(request, error_msg)
            logger.error(error_msg, exc_info=True)
        except Exception as e:
            error_msg = f"An unexpected error occurred while trying to start the background process: {e}"
            messages.error(request, error_msg)
            logger.error(error_msg, exc_info=True)

    def response_add(self, request, obj, post_url_continue=None):
        return HttpResponseRedirect(reverse('admin:editorapp_figmaimportjob_changelist'))
