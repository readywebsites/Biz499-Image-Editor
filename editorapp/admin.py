import logging
import subprocess
import os
import re
from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.urls import reverse
from django.utils.html import format_html
from django.http import HttpResponseRedirect
from .models import Template, FigmaImportJob, Element

logger = logging.getLogger(__name__)

def update_figma_token_in_env(new_token):
    """Safely updates FIGMA_API_TOKEN in backend/.env."""
    env_path = os.path.join(settings.BASE_DIR, '.env')
    try:
        content = ""
        if os.path.exists(env_path):
            with open(env_path, 'r', encoding='utf-8') as f:
                content = f.read()
        if 'FIGMA_API_TOKEN' in content:
            content = re.sub(r'FIGMA_API_TOKEN\s*=.*', f'FIGMA_API_TOKEN="{new_token}"', content)
        else:
            content = content.rstrip() + f'\nFIGMA_API_TOKEN="{new_token}"\n'
        with open(env_path, 'w', encoding='utf-8') as f:
            f.write(content)
        logger.info("Updated FIGMA_API_TOKEN in .env")
    except Exception as e:
        logger.error(f"Failed to update FIGMA_API_TOKEN in .env: {e}")

class TemplateAdminForm(forms.ModelForm):
    figma_api_token = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=True),
        help_text="Optional: Enter or update your Figma Personal Access Token here. It will be saved into backend/.env."
    )
    template_data = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'rows': 5}),
        help_text="JSON template data. Leave empty if auto-importing from Figma URL."
    )

    class Meta:
        model = Template
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            import json
            t_data = self.instance.template_data
            if isinstance(t_data, dict):
                self.initial['template_data'] = json.dumps(t_data, indent=2)
            elif isinstance(t_data, str):
                self.initial['template_data'] = t_data

    def clean_template_data(self):
        data = self.cleaned_data.get('template_data')
        if not data or not data.strip():
            return {}
        if isinstance(data, dict):
            return data
        try:
            import json
            return json.loads(data)
        except Exception as e:
            raise forms.ValidationError(f"Invalid JSON format: {e}")

    def clean(self):
        cleaned_data = super().clean()
        token = cleaned_data.get('figma_api_token')
        if token and token.strip():
            clean_token = token.strip()
            update_figma_token_in_env(clean_token)
            os.environ['FIGMA_API_TOKEN'] = clean_token
            settings.FIGMA_API_TOKEN = clean_token

        figma_url = cleaned_data.get('figma_url')
        name = cleaned_data.get('name') or "Figma Template"

        # Check if figma_url is new or changed
        figma_url_changed = False
        if self.instance and self.instance.pk:
            orig = Template.objects.filter(pk=self.instance.pk).first()
            figma_url_changed = orig and orig.figma_url != figma_url
        else:
            figma_url_changed = bool(figma_url)

        if figma_url and figma_url_changed:
            from .services.figma_importer import FigmaImporter
            file_key, node_id = FigmaImporter.parse_figma_url(figma_url)
            if not file_key:
                self.add_error('figma_url', "Could not extract a valid Figma File Key from the URL. Please check your link.")
            else:
                try:
                    importer = FigmaImporter()
                    result = importer.import_from_url(figma_url, name, api_token=token or None)
                    
                    cleaned_data['template_data'] = result['template_data']
                    cleaned_data['background_image'] = result['background_image_path']
                    cleaned_data['width'] = result['width']
                    cleaned_data['height'] = result['height']
                    
                    self.instance.template_data = result['template_data']
                    self.instance.background_image = result['background_image_path']
                    self.instance.width = result['width']
                    self.instance.height = result['height']
                    
                    self._import_succeeded = True
                    self._element_count = len(result['template_data'].get('elements', []))
                except Exception as e:
                    logger.warning(f"Figma auto-import validation failed: {e}")
                    self.add_error('figma_url', f"Figma Auto-Import Failed: {e}")

        # Ensure template_data defaults to an empty dict if not set
        if not cleaned_data.get('template_data'):
            cleaned_data['template_data'] = {}
            self.instance.template_data = {}

        return cleaned_data

@admin.register(Element)
class ElementAdmin(admin.ModelAdmin):
    list_display = ('name', 'element_type', 'category', 'created_at')
    list_filter = ('element_type', 'category')
    search_fields = ('name', 'category', 'src')

@admin.register(Template)
class TemplateAdmin(admin.ModelAdmin):
    form = TemplateAdminForm
    list_display = ('name', 'category', 'status', 'element_count_display', 'width', 'height', 'created_at', 'updated_at')
    list_filter = ('status', 'category')
    search_fields = ('name', 'description', 'figma_url')
    prepopulated_fields = {'slug': ('name',)}
    date_hierarchy = 'created_at'
    ordering = ('status', '-created_at')
    readonly_fields = ('created_at', 'updated_at')

    fieldsets = (
        ("Figma Automated Import (Just enter Title & Figma URL)", {
            'fields': ('name', 'figma_url', 'figma_api_token', 'category', 'status', 'description', 'slug')
        }),
        ('Template Data (Populated automatically from Figma, or edit manually)', {
            'classes': ('collapse',),
            'fields': ('template_data', 'background_image', 'width', 'height')
        }),
        ('Manual Image Uploads (Optional fallback)', {
            'classes': ('collapse',),
            'fields': (
                'image_1', 'image_2', 'image_3', 'image_4', 'image_5',
                'image_6', 'image_7', 'image_8', 'image_9', 'image_10',
                'image_11', 'image_12', 'image_13', 'image_14', 'image_15',
                'image_16', 'image_17', 'image_18', 'image_19', 'image_20'
            )
        }),
        ('Read-only Details', {
            'classes': ('collapse',),
            'fields': ('created_at', 'updated_at', 'thumbnail')
        })
    )

    def element_count_display(self, obj):
        data = obj.template_data
        if isinstance(data, str):
            try:
                import json
                data = json.loads(data)
            except Exception:
                data = {}
        elif not isinstance(data, dict):
            data = {}
        elements = data.get('elements', []) if isinstance(data, dict) else []
        return f"{len(elements)} elements"
    element_count_display.short_description = "Layers"

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)

        if getattr(form, '_import_succeeded', False):
            count = getattr(form, '_element_count', len(obj.template_data.get('elements', [])))
            messages.success(
                request,
                f"🎉 Successfully imported Figma design '{obj.name}' with {count} editable elements! "
                "All vector SVGs, photos, typography, and background have been saved and are ready in the editor."
            )

class FigmaImportJobForm(forms.ModelForm):
    figma_api_token = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=True),
        help_text="Optional: Enter or update your Figma Personal Access Token here. It will be saved into backend/.env."
    )

    class Meta:
        model = FigmaImportJob
        fields = '__all__'

    def clean(self):
        cleaned_data = super().clean()
        token = cleaned_data.get('figma_api_token')
        if token and token.strip():
            clean_token = token.strip()
            update_figma_token_in_env(clean_token)
            os.environ['FIGMA_API_TOKEN'] = clean_token
            settings.FIGMA_API_TOKEN = clean_token
        return cleaned_data

@admin.register(FigmaImportJob)
class FigmaImportJobAdmin(admin.ModelAdmin):
    form = FigmaImportJobForm
    list_display = ('name', 'status', 'created_at', 'template')
    list_filter = ('status',)
    readonly_fields = ('status', 'error_message', 'template', 'created_at', 'updated_at')
    search_fields = ('name', 'figma_url')
    ordering = ('-created_at',)

    fieldsets = (
        (None, {
            'fields': ('name', 'figma_url', 'figma_api_token')
        }),
        ('Job Status', {
            'classes': ('collapse',),
            'fields': readonly_fields,
        }),
    )

    def save_model(self, request, obj, form, change):
        if change:
            obj.status = 'pending'
            obj.template = None
            obj.error_message = None
        
        super().save_model(request, obj, form, change)

        # Process import
        try:
            token = form.cleaned_data.get('figma_api_token') if form else None
            from .services.figma_importer import FigmaImporter
            importer = FigmaImporter()
            result = importer.import_from_url(obj.figma_url, obj.name, api_token=token or None)

            template = Template.objects.create(
                name=obj.name,
                figma_url=obj.figma_url,
                template_data=result['template_data'],
                background_image=result['background_image_path'],
                width=result['width'],
                height=result['height'],
                status='published'
            )

            obj.status = 'completed'
            obj.template = template
            obj.error_message = None
            obj.save()

            element_count = len(result['template_data'].get('elements', []))
            messages.success(
                request,
                f"🎉 Figma import job completed! Template '{template.name}' created with {element_count} editable elements."
            )
        except Exception as e:
            obj.status = 'failed'
            obj.error_message = str(e)
            obj.save()
            logger.error(f"FigmaImportJob failed: {e}", exc_info=True)
            messages.error(request, f"Figma Import Failed: {e}")

    def response_add(self, request, obj, post_url_continue=None):
        return HttpResponseRedirect(reverse('admin:editorapp_figmaimportjob_changelist'))
