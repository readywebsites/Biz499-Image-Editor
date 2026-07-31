import os
import json
from django.core.management.base import BaseCommand
from django.conf import settings
from editorapp.models import Template, TemplateEditSession

class Command(BaseCommand):
    help = 'Fixes the coordinate mismatch for figma templates by updating them to match template_bundle/template.json.'

    def handle(self, *args, **options):
        bundle_path = os.path.join(settings.BASE_DIR, '..', 'template_bundle', 'template.json')
        if not os.path.exists(bundle_path):
            self.stdout.write(self.style.ERROR(f"Bundle path does not exist: {bundle_path}"))
            return

        with open(bundle_path, 'r', encoding='utf-8') as f:
            bundle_data = json.load(f)

        bundle_elements = {el['id']: el for el in bundle_data.get('elements', [])}
        self.stdout.write(f"Loaded {len(bundle_elements)} elements from template_bundle.")

        def fix_elements(template_data):
            if not template_data or 'elements' not in template_data:
                return False, template_data
            
            modified = False
            new_elements = []
            for el in template_data['elements']:
                el_id = el.get('id')
                if el_id in bundle_elements:
                    correct_el = bundle_elements[el_id]
                    # Check if coordinates/size match
                    el_modified = False
                    for k in ['x', 'y', 'width', 'height']:
                        if el.get(k) != correct_el.get(k):
                            el[k] = correct_el[k]
                            el_modified = True
                            modified = True
                    if el_modified:
                        self.stdout.write(f"  Adjusted element {el_id} ({el.get('name')})")
                new_elements.append(el)
            template_data['elements'] = new_elements
            return modified, template_data

        # Fix templates
        for t in Template.objects.all():
            self.stdout.write(f"Checking template ID {t.id} ({t.name})...")
            modified, updated_data = fix_elements(t.template_data)
            if modified:
                t.template_data = updated_data
                t.save()
                self.stdout.write(self.style.SUCCESS(f"Saved template ID {t.id}"))

        # Fix edit sessions
        for s in TemplateEditSession.objects.all():
            self.stdout.write(f"Checking session ID {s.id} for template '{s.template.name}'...")
            modified, updated_data = fix_elements(s.template_data)
            if modified:
                s.template_data = updated_data
                s.save()
                self.stdout.write(self.style.SUCCESS(f"Saved TemplateEditSession ID {s.id}"))

        self.stdout.write(self.style.SUCCESS("Finished updating coordinates."))
