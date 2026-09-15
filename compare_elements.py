import json

bundle_data = json.load(open('../template_bundle/template.json', encoding='utf-8', errors='replace'))
media_data = json.load(open('media/figma_images/template.json', encoding='utf-8', errors='replace'))

b_elems = {e['id']: e for e in bundle_data.get('elements', [])}
m_elems = {e['id']: e for e in media_data.get('elements', [])}

print("=== ONLY IN MEDIA ===")
for eid, e in m_elems.items():
    if eid not in b_elems:
        print(f"  {eid}: {e.get('name')} | type={e.get('type')} | file={e.get('imageFileName')}")

print("\n=== ONLY IN BUNDLE ===")
for eid, e in b_elems.items():
    if eid not in m_elems:
        print(f"  {eid}: {e.get('name')} | type={e.get('type')} | file={e.get('imageFileName')}")

print("\n=== IN BOTH (COMPARING POS / SIZE) ===")
for eid in b_elems:
    if eid in m_elems:
        be = b_elems[eid]
        me = m_elems[eid]
        b_box = (be.get('x'), be.get('y'), be.get('width'), be.get('height'))
        m_box = (me.get('x'), me.get('y'), me.get('width'), me.get('height'))
        diff = b_box != m_box
        print(f"  {eid:<8} {be.get('name')[:20]:<20} | Bundle: {b_box} | Media: {m_box} {'*** DIFF ***' if diff else 'MATCH'}")
