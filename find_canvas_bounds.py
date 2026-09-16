from PIL import Image

mb = Image.open('../much-better.png')
print("mb size:", mb.size)

# Find the canvas boundary in mb
# The canvas has a border or background
# Let's inspect horizontal line at y = mb.height // 2
y = mb.height // 2
for x in range(0, mb.width, 20):
    print(f"x={x}: {mb.getpixel((x, y))}")
