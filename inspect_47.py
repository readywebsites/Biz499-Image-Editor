import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'image_editor.settings')
django.setup()
from editorapp.models import Template

t = Template.objects.get(id=47)
elems = t.template_data.get('elements', [])
print(f"Template {t.id} ({t.name}):")
for i, e in enumerate(elems):
    print(f"[{i:2d}] id={e.get('id'):<25} name={str(e.get('name'))[:30]:<30} type={e.get('type'):<8} pos=({e.get('x')}, {e.get('y')}) size=({e.get('width')}, {e.get('height')}) file={e.get('imageFileName')} src={e.get('src')}")
