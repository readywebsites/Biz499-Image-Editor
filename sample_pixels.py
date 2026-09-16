from PIL import Image

img = Image.open('much-better.png')
print(f"Image size: {img.width}x{img.height}")

# Let's sample a grid across the image
w, h = img.size
for y_pct in [0.1, 0.25, 0.5, 0.75, 0.9]:
    row = []
    for x_pct in [0.1, 0.3, 0.5, 0.7, 0.85]:
        x = int(w * x_pct)
        y = int(h * y_pct)
        pixel = img.getpixel((x, y))
        row.append(f"({x_pct:.2f},{y_pct:.2f}): {pixel[:3]}")
    print(" | ".join(row))
