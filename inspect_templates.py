import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'image_editor.settings')
django.setup()

from editorapp.models import Template

t = Template.objects.get(id=47)
for i in range(min(4, len(t.template_data['elements']))):
    e = t.template_data['elements'][i]
    print(f"[{i}] id={e.get('id')} name={e.get('name')} type={e.get('type')} file={e.get('imageFileName')} src={e.get('src')}")
