"""Gera os assets FI do sitter a partir da identidade oficial (ID VISUAL FI 2026).

- fi.ico ............ ícone do .exe (símbolo liquid chrome sobre preto)
- logomark.png ...... FEITIÇARIA [símbolo cromado] INDUSTRIAL, layout da Main Logo
- icon64.b64 / logomark.b64 ... PNG em base64 para embutir no sitter_fi.py

Uso: python make_assets.py "<pasta ID VISUAL FI 2026>" <pasta_saida>
"""
import base64, io, sys
from PIL import Image

idv, out = sys.argv[1], sys.argv[2]
chrome = Image.open(f"{idv}/Simbolo cromado.png").convert("RGBA")
chrome = chrome.crop(chrome.getchannel("A").getbbox())
main = Image.open(f"{idv}/Logos/PNG/Main Logo White.png").convert("RGBA")


def b64(im):
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode()


def fit(im, w, h):
    k = min(w / im.width, h / im.height)
    return im.resize((round(im.width * k), round(im.height * k)), Image.LANCZOS)


# --- ícone ---------------------------------------------------------------
S = 256
icon = Image.new("RGBA", (S, S), (0, 0, 0, 255))
sym = fit(chrome, S * 0.86, S * 0.86)
icon.alpha_composite(sym, ((S - sym.width) // 2, (S - sym.height) // 2))
icon.save(f"{out}/fi.ico", sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
open(f"{out}/icon64.b64", "w").write(b64(icon.resize((64, 64), Image.LANCZOS)))

# --- logomarca: troca o símbolo flat da Main Logo pelo cromado -------------
alpha = main.getchannel("A")
cols = [any(alpha.getpixel((x, y)) for y in range(0, main.height, 2)) for x in range(main.width)]
gaps, x = [], 0
while x < main.width:  # trechos vazios entre colunas com tinta
    if not cols[x]:
        s = x
        while x < main.width and not cols[x]:
            x += 1
        if 0 < s and x < main.width:
            gaps.append((x - s, s, x))
    x += 1
(_, g1s, g1e), (_, g2s, g2e) = sorted(sorted(gaps, reverse=True)[:2], key=lambda g: g[1])
sym_box = alpha.crop((g1e, 0, g2s, main.height)).getbbox()
sx0, sy0, sx1, sy1 = g1e + sym_box[0], sym_box[1], g1e + sym_box[2], sym_box[3]
print("símbolo flat em", (sx0, sy0, sx1, sy1))
logo = main.copy()
logo.paste((0, 0, 0, 0), (sx0, 0, sx1, main.height))
sym = fit(chrome, (sx1 - sx0) * 1.08, (sy1 - sy0) * 1.25)  # cromado tem órbita mais aberta
cx, cy = (sx0 + sx1) // 2, (sy0 + sy1) // 2
logo.alpha_composite(sym, (cx - sym.width // 2, cy - sym.height // 2))
logo = logo.crop(logo.getchannel("A").getbbox())
logo.save(f"{out}/logomark.png")
small = fit(logo, 10000, 72)  # 72 px de altura; o app reduz pela metade em telas 100–125%
open(f"{out}/logomark.b64", "w").write(b64(small))
print("logomark", logo.size, "->", small.size)
