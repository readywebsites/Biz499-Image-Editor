import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'image_editor.settings')
django.setup()
from editorapp.models import Template

for tid in [54, 47, 26, 24, 22]:
    try:
        t = Template.objects.get(id=tid)
        elements = t.template_data.get('elements', [])
        print(f"=== Template {t.id} ({t.name}) - elements: {len(elements)} ===")
        for i, e in enumerate(elements[:8]):
            print(f"  [{i}] id={e.get('id')} name={str(e.get('name'))[:20]} type={e.get('type')} file={e.get('imageFileName')}")
    except Exception as err:
        print(f"Error {tid}: {err}")
