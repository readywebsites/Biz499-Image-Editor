import json

d = json.load(open('template_bundle/template.json'))
for i, e in enumerate(d['elements']):
    print(f"[{i:2d}] id={e.get('id'):<8} name={str(e.get('name'))[:25]:<25} type={e.get('type'):<8} pos=({e.get('x')}, {e.get('y')}) size=({e.get('width')}, {e.get('height')}) file={e.get('imageFileName')} src={e.get('src')}")
