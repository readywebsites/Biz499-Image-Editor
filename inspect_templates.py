import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'image_editor.settings')
django.setup()

from editorapp.models import Template

t = Template.objects.order_by('-id').first()
print(f"Latest template ID: {t.id}, Name: {t.name}, Created: {t.created_at}")
elements = t.template_data.get('elements', [])
print(f"Elements count: {len(elements)}")
for i, e in enumerate(elements):
    print(f"[{i:2d}] id={e.get('id'):<8} name={str(e.get('name'))[:30]:<30} type={e.get('type'):<8} file={e.get('imageFileName')} src={e.get('src')}")

