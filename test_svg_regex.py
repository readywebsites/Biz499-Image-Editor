import re

svg = '<svg xmlns="http://www.w3.org/2000/svg" width="1em" height="1em" viewBox="0 0 24 24"><path fill="#ffffff" d="M13 16h-2c-.55 0-1-.45-1-1H3.01v4c0 1.1.9 2 2 2H19c1.1 0 2-.9 2-2v-4h-7c0 .55-.45 1-1 1m7-9h-4c0-2.21-1.79-4-4-4S8 4.79 8 7H4c-1.1 0-2 .9-2 2v3c0 1.11.89 2 2 2h6v-1c0-.55.45-1 1-1h2c.55 0 1 .45 1 1v1h6c1.1 0 2-.9 2-2V9c0-1.1-.9-2-2-2M10 7c0-1.1.9-2 2-2s2 .9 2 2H9.99z"/></svg>'

# JavaScript:
# let processedSvg = svgContent
#   .replace(/<svg([^>]*)(width|height)="[^"]*"/gi, '<svg$1')
#   .replace(/<svg([^>]*)preserveAspectRatio="[^"]*"/gi, '<svg$1')
#   .replace(/<svg/gi, `<svg width="100%" height="100%" ${aspectAttr}`);

# Notice /<svg([^>]*)(width|height)="[^"]*"/gi
# In JS, this matches from <svg until the FIRST width or height, because [^>]* is GREEDY!
# So <svg ... width="1em" height="1em" ...>
# [^>]* matches ' xmlns="..." width="1em" ' and then (width|height)="[^"]*" matches 'height="1em"'!
# And width="1em" is left alone!

s1 = re.sub(r'<svg([^>]*)(width|height)="[^"]*"', r'<svg\1', svg, flags=re.I)
print("s1:", s1[:100])
s2 = re.sub(r'<svg', r'<svg width="100%" height="100%" preserveAspectRatio="xMidYMid meet"', s1, flags=re.I)
print("s2:", s2[:150])
