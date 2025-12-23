import fitz
import pytesseract
from PIL import Image
doc = fitz.open("/mnt/c/Users/aaaxx/Downloads/tests/War/العسكرية العربية الاسلامية.pdf")

full_text = ""

for page in doc:
    pix = page.get_pixmap(dpi=300)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    text = pytesseract.image_to_string(img, lang="ara")
    full_text += text + "\n\n"

open("output.txt", "w", encoding="utf-8").write(full_text)
