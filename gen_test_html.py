import json

data = json.load(open('media/figma_images/template.json', encoding='utf-8', errors='replace'))
elements = data.get('elements', [])

html = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
body { margin: 0; background: #0f172a; display: flex; justify-content: center; align-items: center; min-height: 100vh; }
.scaled-container {
    position: relative;
    width: 600px;
    height: 600px;
    overflow: hidden;
    background-color: #008080;
    border-radius: 16px;
    border: 3px solid #6366f1;
}
.canvas {
    position: absolute;
    left: 0; top: 0;
    width: 2000px; height: 2000px;
    transform: scale(0.3);
    transform-origin: top left;
}
.canvas-element {
    position: absolute;
    box-sizing: border-box;
}
</style>
</head>
<body>
<div class="scaled-container">
<div class="canvas">
"""

for idx, el in enumerate(elements):
    x = el.get('x', 0)
    y = el.get('y', 0)
    w = el.get('width', 0)
    h = el.get('height', 0)
    op = el.get('opacity', 1)
    rot = el.get('rotation', 0)
    el_type = el.get('type')
    name = el.get('name', '')
    
    style = f"left: 0px; top: 0px; width: {w}px; height: {h}px; transform: translate({x}px, {y}px) rotate({rot}deg); transform-origin: center center; opacity: {op}; z-index: {idx};"
    
    if el_type == 'IMAGE':
        fname = el.get('imageFileName', '')
        src = f"media/figma_images/{fname}"
        html += f'<div class="canvas-element" style="{style}"><img src="{src}" style="width:100%; height:100%; display:block;" /></div>\n'
    elif el_type == 'TEXT':
        text = el.get('text', '')
        font = el.get('fontFamily', 'sans-serif')
        size = el.get('fontSize', 36)
        color = el.get('color', '#ffffff')
        align = el.get('textAlign', 'left').lower()
        lh = el.get('lineHeight', size)
        html += f'<div class="canvas-element" style="{style} font-size: {size}px; color: {color}; text-align: {align}; line-height: {lh}px; font-family: {font}, sans-serif; white-space: pre-wrap;">{text}</div>\n'
    elif el_type == 'ICON':
        html += f'<div class="canvas-element" style="{style}"></div>\n'

html += """</div>
</div>
</body>
</html>
"""

with open('test_render_media.html', 'w', encoding='utf-8') as f:
    f.write(html)
print("Wrote test_render_media.html")
