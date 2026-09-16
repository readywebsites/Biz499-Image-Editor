from PIL import Image

mb = Image.open('../much-better.png')
trm = Image.open('../test_render_media.png')

print("much-better size:", mb.size)
print("test_render_media size:", trm.size)

# Compare top-left corner
print("mb (50, 50):", mb.getpixel((50, 50)))
print("trm (50, 50):", trm.getpixel((50, 50)))

# Compare top-right corner
print("mb (500, 200):", mb.getpixel((500, 200)))
print("trm (500, 200):", trm.getpixel((500, 200)))
