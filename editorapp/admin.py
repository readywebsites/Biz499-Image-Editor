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
        if figma_url:
            from .services.figma_importer import FigmaImporter
            file_key, _ = FigmaImporter.parse_figma_url(figma_url)
            if not file_key:
                self.add_error('figma_url', "Could not extract a valid Figma File Key from the URL. Please check your link.")

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
    list_display = ('name', 'category', 'status', 'import_status_display', 'width', 'height', 'created_at', 'updated_at')
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

    def import_status_display(self, obj):
        data = obj.template_data
        elements = data.get('elements', []) if isinstance(data, dict) else []
        if elements:
            return format_html('<span style="color: #166534; font-weight: 600;">✅ Ready ({} layers)</span>', len(elements))
        
        # Check if there is an active FigmaImportJob for this template
        job = FigmaImportJob.objects.filter(template=obj).order_by('-created_at').first()
        if job:
            if job.status == 'processing':
                return format_html('<span style="color: #1e40af; font-weight: 600;">⚙️ Importing...</span>')
            elif job.status == 'pending':
                return format_html('<span style="color: #854d0e; font-weight: 600;">⏳ Queued...</span>')
            elif job.status == 'failed':
                return format_html('<span style="color: #991b1b; font-weight: 600;" title="{}">❌ Import Failed</span>', job.error_message or '')
        
        return "Empty (Draft)"
    import_status_display.short_description = "Content / Layers"

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)

        # Non-blocking: If figma_url is provided and template has no elements, trigger background import
        has_elements = bool(obj.template_data and obj.template_data.get('elements'))
        if obj.figma_url and not has_elements:
            from .services.figma_runner import start_figma_import_background
            active_job = FigmaImportJob.objects.filter(template=obj, status__in=['pending', 'processing']).first()
            if not active_job:
                job = FigmaImportJob.objects.create(
                    name=obj.name,
                    figma_url=obj.figma_url,
                    status='pending',
                    template=obj
                )
                start_figma_import_background(job.id)
                messages.info(
                    request,
                    f"🚀 Figma import for '{obj.name}' has started in the background. "
                    "All editable layers and assets are being downloaded and will appear once completed. "
                    "You can track progress in Figma Import Jobs."
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

        figma_url = cleaned_data.get('figma_url')
        if figma_url:
            from .services.figma_importer import FigmaImporter
            file_key, _ = FigmaImporter.parse_figma_url(figma_url)
            if not file_key:
                self.add_error('figma_url', "Could not extract a valid Figma File Key from the URL. Please check your link.")
        return cleaned_data

@admin.register(FigmaImportJob)
class FigmaImportJobAdmin(admin.ModelAdmin):
    form = FigmaImportJobForm
    list_display = ('name', 'status_badge', 'template_link', 'error_summary', 'created_at')
    list_filter = ('status',)
    readonly_fields = ('status', 'error_message', 'template', 'created_at', 'updated_at')
    search_fields = ('name', 'figma_url')
    ordering = ('-created_at',)

    fieldsets = (
        (None, {
            'fields': ('name', 'figma_url', 'figma_api_token')
        }),
        ('Job Status', {
            'fields': readonly_fields,
        }),
    )

    def status_badge(self, obj):
        status_colors = {
            'pending': ('#fef08a', '#854d0e', '⏳ Pending'),
            'processing': ('#bfdbfe', '#1e40af', '⚙️ Processing...'),
            'completed': ('#bbf7d0', '#166534', '✅ Completed'),
            'failed': ('#fecaca', '#991b1b', '❌ Failed'),
        }
        bg, color, text = status_colors.get(obj.status, ('#e2e8f0', '#334155', obj.status.title()))
        badge_html = (
            f'<span style="background: {bg}; color: {color}; padding: 3px 10px; '
            f'border-radius: 9999px; font-weight: 600; font-size: 12px; display: inline-block;">{text}</span>'
        )
        if obj.status in ('pending', 'processing'):
            badge_html += '<script>if(!window._figma_refresher){window._figma_refresher=setTimeout(function(){location.reload();}, 4000);}</script>'
        return format_html(badge_html)
    status_badge.short_description = "Status"

    def template_link(self, obj):
        if obj.template:
            admin_url = reverse('admin:editorapp_template_change', args=[obj.template.id])
            editor_url = f"/editor/{obj.template.slug}"
            return format_html(
                '<a href="{}" style="font-weight: 500;">{}</a> '
                '<a href="{}" target="_blank" style="margin-left: 8px; color: #4f46e5; text-decoration: none; font-weight: 600;">🎨 Open Editor &rarr;</a>',
                admin_url, obj.template.name, editor_url
            )
        return "-"
    template_link.short_description = "Generated Template"

    def error_summary(self, obj):
        if not obj.error_message:
            return "-"
        msg = obj.error_message
        preview = msg[:80] + ("..." if len(msg) > 80 else "")
        return format_html('<span style="color: #dc2626; font-size: 12px;" title="{}">{}</span>', msg, preview)
    error_summary.short_description = "Error Details"

    def save_model(self, request, obj, form, change):
        if change and obj.status == 'failed':
            obj.status = 'pending'
            obj.error_message = None
        elif not change:
            obj.status = 'pending'
        
        super().save_model(request, obj, form, change)

        # Trigger background processing immediately without blocking the request
        from .services.figma_runner import start_figma_import_background
        start_figma_import_background(obj.id)

        messages.info(
            request,
            f"🚀 Figma import job '{obj.name}' has been started in the background. "
            "The status will update automatically once completed."
        )

    def response_add(self, request, obj, post_url_continue=None):
        return HttpResponseRedirect(reverse('admin:editorapp_figmaimportjob_changelist'))

