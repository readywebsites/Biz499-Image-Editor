from PIL import Image

img = Image.open('../much-better.png')
# Canvas is 2000x2000. In much-better.png, canvas is roughly w=600, h=600
# pos=(102, 93), size=(100, 100) on 2000x2000 canvas
# In much-better.png, let's find the canvas bounds first
w, h = img.size
print("Image size:", w, h)

# Check top-left area: x from 20 to 100, y from 20 to 100
for y in range(20, 80, 10):
    row = [f"{img.getpixel((x, y))[:3]}" for x in range(30, 120, 15)]
    print(f"y={y}:", " ".join(row))
