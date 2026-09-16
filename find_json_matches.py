import os
import json

root = r'C:\Image-Editor'
for dirpath, dirnames, filenames in os.walk(root):
    if 'node_modules' in dirpath or '.git' in dirpath:
        continue
    for fname in filenames:
        if fname.endswith('.json'):
            fpath = os.path.join(dirpath, fname)
            try:
                content = open(fpath, 'r', encoding='utf-8', errors='ignore').read()
                if '4:10' in content or 'round-business-center' in content:
                    print(f"Found match in: {fpath} (size={len(content)})")
            except Exception as e:
                pass
