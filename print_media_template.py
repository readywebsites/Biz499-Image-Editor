import json

data = json.load(open('media/figma_images/template.json', encoding='utf-8', errors='replace'))
print(f"Elements count: {len(data.get('elements', []))}")
for i, e in enumerate(data.get('elements', [])):
    print(f"[{i:2d}] id={e.get('id'):<8} name={e.get('name')[:30]:<30} type={e.get('type'):<8} pos=({e.get('x')}, {e.get('y')}) size=({e.get('width')}, {e.get('height')}) file={e.get('imageFileName')}")
