from django.db import models
from django.utils.text import slugify

class Template(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('published', 'Published'),
    ]

    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True, blank=True)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=100, blank=True)
    thumbnail = models.URLField(max_length=200, blank=True)
    template_data = models.JSONField(default=dict, blank=True)
    background_image = models.ImageField(upload_to='template_backgrounds/', blank=True, null=True)
    width = models.PositiveIntegerField(blank=True, null=True)
    height = models.PositiveIntegerField(blank=True, null=True)
    figma_url = models.URLField(max_length=500, blank=True, null=True, help_text="Paste a Figma file/frame URL to auto-import the design.")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='draft')
    session_id = models.CharField(max_length=255, blank=True, null=True, db_index=True)
    is_user_design = models.BooleanField(default=False)
    
    # Support up to 20 admin-uploadable editable images (supports raster PNG/JPG and vector SVG)
    image_1 = models.FileField(upload_to='template_images/', blank=True, null=True)
    image_2 = models.FileField(upload_to='template_images/', blank=True, null=True)
    image_3 = models.FileField(upload_to='template_images/', blank=True, null=True)
    image_4 = models.FileField(upload_to='template_images/', blank=True, null=True)
    image_5 = models.FileField(upload_to='template_images/', blank=True, null=True)
    image_6 = models.FileField(upload_to='template_images/', blank=True, null=True)
    image_7 = models.FileField(upload_to='template_images/', blank=True, null=True)
    image_8 = models.FileField(upload_to='template_images/', blank=True, null=True)
    image_9 = models.FileField(upload_to='template_images/', blank=True, null=True)
    image_10 = models.FileField(upload_to='template_images/', blank=True, null=True)
    image_11 = models.FileField(upload_to='template_images/', blank=True, null=True)
    image_12 = models.FileField(upload_to='template_images/', blank=True, null=True)
    image_13 = models.FileField(upload_to='template_images/', blank=True, null=True)
    image_14 = models.FileField(upload_to='template_images/', blank=True, null=True)
    image_15 = models.FileField(upload_to='template_images/', blank=True, null=True)
    image_16 = models.FileField(upload_to='template_images/', blank=True, null=True)
    image_17 = models.FileField(upload_to='template_images/', blank=True, null=True)
    image_18 = models.FileField(upload_to='template_images/', blank=True, null=True)
    image_19 = models.FileField(upload_to='template_images/', blank=True, null=True)
    image_20 = models.FileField(upload_to='template_images/', blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.name) or "template"
            slug = base_slug
            counter = 1
            while Template.objects.filter(slug=slug).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug

        # Check if figma_url has changed to avoid unnecessary API requests and overwrites
        figma_url_changed = False
        if self.pk:
            try:
                orig = Template.objects.get(pk=self.pk)
                figma_url_changed = orig.figma_url != self.figma_url
            except Template.DoesNotExist:
                figma_url_changed = bool(self.figma_url)
        else:
            figma_url_changed = bool(self.figma_url)

        # Ensure template_data is parsed if provided as a JSON string
        if isinstance(self.template_data, str):
            try:
                import json
                self.template_data = json.loads(self.template_data) if self.template_data.strip() else {}
            except Exception:
                self.template_data = {}
        elif not isinstance(self.template_data, dict):
            self.template_data = {}

        has_elements = bool(self.template_data.get('elements'))

        if figma_url_changed and self.figma_url and not has_elements:
            try:
                from .services.figma_importer import FigmaImporter
                importer = FigmaImporter()
                result = importer.import_from_url(self.figma_url, self.name)
                
                self.template_data = result['template_data']
                self.background_image = result['background_image_path']
                self.width = result['width']
                self.height = result['height']
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Auto-import from Figma URL failed: {e}", exc_info=True)
                from django.core.exceptions import ValidationError
                raise ValidationError(f"Figma Auto-Import Failed: {e}")

        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['-created_at']

class FigmaImportJob(models.Model):
    """A model to track the status of a Figma import job."""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]

    name = models.CharField(max_length=255, help_text="The name for the new template.")
    figma_url = models.URLField(help_text="The full URL of the Figma file to import.")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    error_message = models.TextField(blank=True, null=True)
    template = models.ForeignKey(Template, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    class Meta:
        verbose_name = "Figma Import Job"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.get_status_display()})"


class TemplateEditSession(models.Model):
    session_id = models.CharField(max_length=255, db_index=True)
    template = models.ForeignKey(Template, on_delete=models.CASCADE, related_name='edit_sessions')
    template_data = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('session_id', 'template')
        ordering = ['-updated_at']

    def __str__(self):
        return f"Session {self.session_id} - Template {self.template.name}"


class Element(models.Model):
    ELEMENT_TYPES = [
        ('svg', 'SVG Vector'),
        ('shape', 'Shape'),
        ('image', 'Image'),
        ('icon', 'Icon'),
    ]

    name = models.CharField(max_length=255)
    element_type = models.CharField(max_length=20, choices=ELEMENT_TYPES, default='svg')
    category = models.CharField(max_length=100, default='General')
    src = models.CharField(max_length=500, blank=True, help_text="Path or URL to SVG or image file")
    svg_content = models.TextField(blank=True, help_text="Raw SVG content string if stored directly")
    file = models.FileField(upload_to='elements/', blank=True, null=True, help_text="Upload custom SVG/Image file")
    width = models.FloatField(default=100)
    height = models.FloatField(default=100)
    data_json = models.JSONField(default=dict, blank=True, help_text="Custom element schema payload")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.element_type})"
