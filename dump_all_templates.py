import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'image_editor.settings')
django.setup()
from editorapp.models import Template

for t in Template.objects.all().order_by('-id'):
    elems = t.template_data.get('elements', [])
    elem_names = [e.get('name') for e in elems]
    print(f"ID={t.id:2d} | Name={t.name:<25} | Created={str(t.created_at)[:19]} | Elements={len(elems)} | Has briefcase={'ic:round-business-center' in str(elem_names)} | Has mask={'Mask Group' in str(elem_names)}")
