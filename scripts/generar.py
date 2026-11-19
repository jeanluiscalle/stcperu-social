#!/usr/bin/env python3
"""Genera las próximas publicaciones de STC Perú.

Toma el siguiente tema sin usar de contenido/temas.json, pide a OpenAI una
fotografía realista SIN texto y la diseña con uno de varios formatos
(portada, mito, carrusel, checklist, dato). El texto lo pone este script con
las fuentes de la marca, así nunca sale con faltas de ortografía.

Cada publicación queda en estado «borrador» con su fecha programada; solo se
publica cuando se aprueba (workflow «Aprobar publicaciones»).

Uso:
  python scripts/generar.py                    # 1 publicación
  python scripts/generar.py --cantidad 3
  python scripts/generar.py --tema starlink    # un tema concreto
  python scripts/generar.py --redisenar ID     # rehace el diseño con la foto guardada (sin costo)
  python scripts/generar.py --sin-ia           # fondo de prueba, sin OpenAI
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

RAIZ = Path(__file__).resolve().parent.parent
TEMAS = RAIZ / "contenido" / "temas.json"
CONFIG = RAIZ / "contenido" / "config.json"
POSTS = RAIZ / "posts"
INDICE = POSTS / "index.json"
FUENTES = RAIZ / "assets" / "fonts"

W, H = 1080, 1350
M = 72
PERU = timezone(timedelta(hours=-5))
BLANCO = (255, 255, 255)


# ================================================================ utilidades
def leer_json(ruta: Path, defecto):
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else defecto


def guardar_json(ruta: Path, datos) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def rgb(valor: str) -> tuple[int, int, int]:
    valor = valor.lstrip("#")
    return tuple(int(valor[i:i + 2], 16) for i in (0, 2, 4))


def anton(t: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FUENTES / "Anton-Regular.ttf"), t)


def figtree(t: int, peso: str = "SemiBold") -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FUENTES / "Figtree-VF.ttf"), t)
    f.set_variation_by_name(peso)
    return f


def cubrir(img: Image.Image, ancho: int, alto: int, foco: tuple[float, float] = (0.5, 0.5)) -> Image.Image:
    escala = max(ancho / img.width, alto / img.height)
    img = img.resize((round(img.width * escala), round(img.height * escala)), Image.LANCZOS)
    x = int((img.width - ancho) * foco[0])
    y = int((img.height - alto) * foco[1])
    return img.crop((x, y, x + ancho, y + alto))


def degradado(lienzo: Image.Image, color, y0: int, y1: int, a0: int, a1: int, curva: float = 1.3) -> None:
    """Superpone un degradado vertical de color entre y0 y y1 (opacidad a0 → a1)."""
    alto = max(1, y1 - y0)
    mascara = Image.new("L", (1, alto))
    for y in range(alto):
        t = (y / (alto - 1)) ** curva if alto > 1 else 1
        mascara.putpixel((0, y), int(a0 + (a1 - a0) * t))
    lienzo.paste(Image.new("RGB", (lienzo.width, alto), color), (0, y0), mascara.resize((lienzo.width, alto)))


def velo(lienzo: Image.Image, color, opacidad: int, caja=None) -> None:
    caja = caja or (0, 0, lienzo.width, lienzo.height)
    capa = Image.new("RGB", (caja[2] - caja[0], caja[3] - caja[1]), color)
    lienzo.paste(capa, caja[:2], Image.new("L", capa.size, opacidad))


def redondear(img: Image.Image, radio: int) -> tuple[Image.Image, Image.Image]:
    mascara = Image.new("L", img.size, 0)
    ImageDraw.Draw(mascara).rounded_rectangle((0, 0, *img.size), radius=radio, fill=255)
    return img, mascara


def partir(texto: str, fuente, ancho: int, d: ImageDraw.ImageDraw) -> list[str]:
    lineas, actual = [], ""
    for palabra in texto.split():
        prueba = f"{actual} {palabra}".strip()
        if d.textlength(prueba, font=fuente) <= ancho or not actual:
            actual = prueba
        else:
            lineas.append(actual)
            actual = palabra
    return lineas + ([actual] if actual else [])


def titular(d, texto: str, x: int, y: int, ancho: int, tamanos, max_lineas: int,
            color=BLANCO, resaltar=(), color_resaltado=None, interlinea=1.04, alinear="izq",
            dibujar: bool = True) -> int:
    """Dibuja un titular en Anton (mayúsculas) con palabras resaltadas. Devuelve la y final."""
    texto = texto.upper()
    for t in tamanos:
        f = anton(t)
        lineas = partir(texto, f, ancho, d)
        if len(lineas) <= max_lineas:
            break
    resaltar = {r.upper() for r in resaltar}
    if not dibujar:
        return y + int(t * interlinea) * len(lineas) + int(t * 0.2)
    for linea in lineas:
        ancho_linea = d.textlength(linea, font=f)
        cx = x + (ancho - ancho_linea) / 2 if alinear == "centro" else x
        for i, palabra in enumerate(linea.split(" ")):
            if i:
                cx += d.textlength(" ", font=f)
            tono = color_resaltado if palabra.upper() in resaltar and color_resaltado else color
            d.text((cx, y), palabra, font=f, fill=tono)
            cx += d.textlength(palabra, font=f)
        y += int(t * interlinea)
    return y + int(t * 0.2)   # Anton es alto: deja aire bajo la última línea


def parrafo(d, texto: str, x: int, y: int, ancho: int, fuente, color, interlinea=1.32, alinear="izq") -> int:
    for linea in partir(texto, fuente, ancho, d):
        if alinear == "centro":
            d.text((x + ancho / 2, y), linea, font=fuente, fill=color, anchor="ma")
        else:
            d.text((x, y), linea, font=fuente, fill=color)
        y += int(fuente.size * interlinea)
    return y


def pastilla(d, x: int, y: int, texto: str, fondo, color, t=26, peso="Bold", pad=(22, 12)) -> int:
    f = figtree(t, peso)
    ancho = d.textlength(texto, font=f)
    alto = t + pad[1] * 2
    d.rounded_rectangle((x, y, x + ancho + pad[0] * 2, y + alto), radius=alto // 2, fill=fondo)
    d.text((x + pad[0], y + alto / 2), texto, font=f, fill=color, anchor="lm")
    return int(x + ancho + pad[0] * 2)


def icono_whatsapp(d, cx: int, cy: int, r: int, color) -> None:
    """Burbuja de chat sencilla (no el logo oficial)."""
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=color, width=max(3, r // 6))
    d.polygon([(cx - r * 0.75, cy + r * 0.45), (cx - r * 1.05, cy + r * 1.05), (cx - r * 0.25, cy + r * 0.85)], fill=color)
    d.ellipse((cx - r * 0.35, cy - r * 0.35, cx + r * 0.35, cy + r * 0.35), fill=color)


def boton_whatsapp(d, x: int, y: int, cfg: dict, t: int = 34, texto: str | None = None) -> tuple[int, int]:
    texto = texto or f"Escríbenos: {cfg['whatsapp']}"
    f = figtree(t, "Bold")
    alto = int(t * 2.05)
    ancho = int(d.textlength(texto, font=f) + alto + 40)
    d.rounded_rectangle((x, y, x + ancho, y + alto), radius=alto // 2, fill=cfg["c"]["verde"])
    icono_whatsapp(d, x + alto // 2 + 4, y + alto // 2, int(t * 0.42), BLANCO)
    d.text((x + alto + 6, y + alto / 2), texto, font=f, fill=BLANCO, anchor="lm")
    return x + ancho, y + alto


def marca(d, x: int, y: int, cfg: dict, claro: bool = False) -> None:
    f = anton(40)
    d.text((x, y), "STC PERÚ", font=f, fill=cfg["c"]["navy"] if claro else cfg["c"]["cian"])
    ancho = d.textlength("STC PERÚ", font=f)
    d.text((x + ancho + 14, y + 28), "Servicio técnico · " + cfg["ciudades"], font=figtree(22, "Medium"),
           fill=(70, 88, 125) if claro else (215, 225, 242), anchor="ls")


def puntos_carrusel(d, actual: int, total: int, y: int, claro: bool, cfg: dict) -> None:
    ancho_total = total * 14 + (total - 1) * 10 + 24
    x = W - M - ancho_total
    for i in range(total):
        largo = 38 if i == actual else 14
        color = cfg["c"]["cian"] if i == actual else ((190, 200, 220) if claro else (90, 110, 150))
        d.rounded_rectangle((x, y, x + largo, y + 14), radius=7, fill=color)
        x += largo + 10


def check(d, cx: int, cy: int, r: int, fondo, color) -> None:
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=fondo)
    d.line([(cx - r * 0.45, cy + r * 0.02), (cx - r * 0.1, cy + r * 0.38), (cx + r * 0.5, cy - r * 0.35)],
           fill=color, width=max(4, r // 4), joint="curve")


# ================================================================ formatos
# Todas las publicaciones son carruseles: portada (con estilo según el formato)
# + 3 páginas con los 3 datos + página final con el llamado a WhatsApp.

def indicador_deslizar(d, total: int, cfg: dict) -> None:
    d.text((W - M, H - 92), "DESLIZA  →", font=anton(40), fill=cfg["c"]["cian"], anchor="rm")
    puntos_carrusel(d, 0, total, H - 52, False, cfg)


def portada_foto(foto, tema, cfg, total):
    """Foto a sangre con titular grande y subtítulo."""
    c = cfg["c"]
    img = cubrir(foto, W, H)
    degradado(img, (0, 0, 0), 0, 260, 150, 0, 1.0)
    degradado(img, c["navy"], 470, H, 0, 252, 0.9)
    d = ImageDraw.Draw(img)
    marca(d, M, 56, cfg)
    tam = (96, 88, 80, 72)
    f_sub = figtree(30, "Medium")
    alto_sub = len(partir(tema.get("subtitulo", ""), f_sub, W - 2 * M, d)) * 40 + 10
    y = H - 150 - alto_sub - titular(d, tema["titulo"], M, 0, W - 2 * M, tam, 4, dibujar=False)
    pastilla(d, M, y - 72, tema["categoria"].upper(), c["cian"], c["navy"])
    y = titular(d, tema["titulo"], M, y, W - 2 * M, tam, 4, resaltar=tema.get("resaltar", ()),
                color_resaltado=c["cian"])
    if tema.get("subtitulo"):
        parrafo(d, tema["subtitulo"], M, y + 12, W - 2 * M, f_sub, (220, 229, 245))
    indicador_deslizar(d, total, cfg)
    return img


def portada_mito(foto, tema, cfg, total):
    """Foto arriba, mito tachado y adelanto de la realidad."""
    c = cfg["c"]
    img = Image.new("RGB", (W, H), c["navy"])
    img.paste(cubrir(foto, W, 760, (0.5, 0.4)), (0, 0))
    degradado(img, (0, 0, 0), 0, 220, 140, 0, 1.0)
    degradado(img, c["navy"], 380, 760, 0, 255, 1.1)
    d = ImageDraw.Draw(img)
    marca(d, M, 56, cfg)
    y = titular(d, tema["titulo"], M, 560, W - 2 * M, (88, 80, 72), 3, resaltar=tema.get("resaltar", ()),
                color_resaltado=c["cian"])
    y += 20
    f_mito = figtree(34, "SemiBold")
    l_mito = partir(tema["mito"], f_mito, W - 2 * M - 230, d)
    alto = max(120, len(l_mito) * 46 + 50)
    d.rounded_rectangle((M, y, W - M, y + alto), radius=28, fill=(28, 22, 40))
    d.rounded_rectangle((M, y, M + 10, y + alto), radius=5, fill=c["rojo"])
    pastilla(d, M + 34, y + alto // 2 - 27, "MITO", c["rojo"], BLANCO, t=30, pad=(24, 12))
    ty = y + (alto - len(l_mito) * 46) // 2 - 4
    for linea in l_mito:
        d.text((M + 200, ty), linea, font=f_mito, fill=(236, 236, 244))
        ancho = d.textlength(linea, font=f_mito)
        d.line([(M + 198, ty + 23), (M + 202 + ancho, ty + 23)], fill=c["rojo"], width=4)
        ty += 46
    y += alto + 22
    d.rounded_rectangle((M, y, W - M, y + 110), radius=28, fill=(16, 44, 86))
    d.rounded_rectangle((M, y, M + 10, y + 110), radius=5, fill=c["cian"])
    x = pastilla(d, M + 34, y + 28, "REALIDAD", c["cian"], c["navy"], t=30, pad=(24, 12))
    d.text((x + 24, y + 55), "3 datos que sí debes saber", font=figtree(32, "SemiBold"), fill=BLANCO, anchor="lm")
    indicador_deslizar(d, total, cfg)
    return img


def portada_checklist(foto, tema, cfg, total):
    """Foto arriba y tarjeta clara con los 3 puntos a revisar."""
    c = cfg["c"]
    img = Image.new("RGB", (W, H), c["navy"])
    img.paste(cubrir(foto, W, 780, (0.5, 0.45)), (0, 0))
    degradado(img, (0, 0, 0), 0, 240, 150, 0, 1.0)
    degradado(img, c["navy"], 320, 780, 0, 255, 1.3)
    d = ImageDraw.Draw(img)
    marca(d, M, 56, cfg)
    f = figtree(36, "Bold")
    titulos = [sl["titulo"] for sl in tema["slides"][:3]]
    bloques = [partir(t, f, W - 2 * M - 140, d) for t in titulos]
    alto = 36 + sum(len(b) * 46 + 30 for b in bloques)
    tam = (88, 80, 72)
    fondo = H - 160 - alto
    y = fondo - 26 - titular(d, tema["titulo"], M, 0, W - 2 * M, tam, 3, dibujar=False)
    titular(d, tema["titulo"], M, y, W - 2 * M, tam, 3, resaltar=tema.get("resaltar", ()), color_resaltado=c["cian"])
    d.rounded_rectangle((M, fondo, W - M, fondo + alto), radius=34, fill=c["claro"])
    ty = fondo + 28
    for lineas in bloques:
        check(d, M + 58, ty + 22, 24, c["cian"], c["navy"])
        for linea in lineas:
            d.text((M + 104, ty), linea, font=f, fill=c["navy"])
            ty += 46
        ty += 30
    indicador_deslizar(d, total, cfg)
    return img


def portada_dato(foto, tema, cfg, total):
    """Cifra gigante sobre la foto y 3 mini datos."""
    c = cfg["c"]
    img = cubrir(foto, W, H)
    velo(img, c["navy"], 150)
    degradado(img, c["navy"], 300, H, 40, 250, 0.9)
    d = ImageDraw.Draw(img)
    marca(d, M, 56, cfg)
    pastilla(d, M, 330, tema.get("pastilla", tema["categoria"]).upper(), c["cian"], c["navy"])
    d.text((M - 8, 380), tema["numero"], font=anton(270), fill=c["cian"])
    y = titular(d, tema["etiqueta"], M, 700, W - 2 * M, (76, 68), 2)
    y += 30
    ancho = (W - 2 * M - 2 * 24) // 3
    for i, (valor, texto) in enumerate(tema["datos"]):
        x = M + i * (ancho + 24)
        velo(img, (255, 255, 255), 28, (x, y, x + ancho, y + 170))
        d.rounded_rectangle((x, y, x + ancho, y + 170), radius=26, outline=(120, 150, 200), width=2)
        d.text((x + ancho / 2, y + 30), valor, font=anton(64), fill=BLANCO, anchor="ma")
        d.text((x + ancho / 2, y + 118), texto, font=figtree(28, "Medium"), fill=(210, 222, 242), anchor="ma")
    indicador_deslizar(d, total, cfg)
    return img


def pagina_dato(foto, tema, cfg, i: int, slide: dict, total: int):
    c = cfg["c"]
    focos = [(0.15, 0.3), (0.85, 0.5), (0.5, 0.75)]
    img = Image.new("RGB", (W, H), c["claro"])
    foto_slide = cubrir(foto.resize((foto.width * 2, foto.height * 2)), W - 2 * M, 560, focos[(i - 1) % 3])
    foto_slide, mascara = redondear(foto_slide, 40)
    img.paste(foto_slide, (M, 150), mascara)
    d = ImageDraw.Draw(img)
    marca(d, M, 52, cfg, claro=True)
    d.text((W - M, 74), f"{i}/3", font=figtree(28, "Bold"), fill=(110, 125, 155), anchor="rm")
    num = f"{i:02d}"
    f_num = anton(170)
    d.rounded_rectangle((M + 30, 620, M + 30 + d.textlength(num, font=f_num) + 50, 830), radius=30, fill=c["navy"])
    d.text((M + 55, 618), num, font=f_num, fill=c["cian"])
    y = titular(d, slide["titulo"], M, 870, W - 2 * M, (76, 68, 60), 2, color=c["navy"])
    parrafo(d, slide["texto"], M, y + 12, W - 2 * M, figtree(35, "Medium"), (52, 66, 98))
    d.text((M, H - 52), f"WhatsApp {cfg['whatsapp']}", font=figtree(26, "Bold"), fill=(16, 120, 70), anchor="lm")
    puntos_carrusel(d, i, total, H - 60, True, cfg)
    return img


def pagina_cta(foto, tema, cfg, total: int):
    c = cfg["c"]
    img = cubrir(foto, W, H, (0.5, 0.5)).filter(ImageFilter.GaussianBlur(18))
    velo(img, c["navy"], 225)
    d = ImageDraw.Draw(img)
    marca(d, M, 56, cfg)
    pregunta = tema.get("pregunta_cta", "¿Necesitas ayuda con tu equipo?")
    y = titular(d, pregunta, M, 360, W - 2 * M, (110, 100, 90), 3, resaltar=("AYUDA",),
                color_resaltado=c["cian"], alinear="centro")
    y = parrafo(d, "Te respondemos por WhatsApp con un diagnóstico claro antes de reparar.", M + 40, y + 10,
                W - 2 * M - 80, figtree(34, "Medium"), (220, 229, 245), alinear="centro")
    f = figtree(40, "Bold")
    ancho = d.textlength(f"Escríbenos: {cfg['whatsapp']}", font=f) + 82 + 40
    boton_whatsapp(d, int((W - ancho) / 2), y + 50, cfg, t=40)
    d.text((W / 2, y + 215), cfg["web"], font=figtree(32, "SemiBold"), fill=c["cian"], anchor="ma")
    d.text((W / 2, H - 150), "GUÁRDALO  ·  COMPÁRTELO", font=anton(44), fill=BLANCO, anchor="ma")
    puntos_carrusel(d, total - 1, total, H - 60, False, cfg)
    return img


PORTADAS = {
    "portada": portada_foto,
    "carrusel": portada_foto,
    "mito": portada_mito,
    "checklist": portada_checklist,
    "dato": portada_dato,
}


def armar(foto, tema, cfg) -> list[Image.Image]:
    slides = tema["slides"][:3]
    total = len(slides) + 2
    paginas = [PORTADAS[tema["formato"]](foto, tema, cfg, total)]
    paginas += [pagina_dato(foto, tema, cfg, i, sl, total) for i, sl in enumerate(slides, start=1)]
    paginas.append(pagina_cta(foto, tema, cfg, total))
    return paginas


# ================================================================ foto IA
def prompt_foto(tema: dict) -> str:
    return (
        f"Professional commercial photograph of {tema['escena']}. Shot on a full-frame camera with a 35mm or 50mm "
        "lens, realistic lighting, natural colors, true-to-life textures, shallow depth of field, editorial "
        "advertising quality, authentic real-world environment. Leave calm areas for text. "
        "Do not add captions, watermarks or overlaid text."
    )


def foto_openai(tema: dict, cfg: dict) -> Image.Image:
    clave = os.environ.get("OPENAI_API_KEY")
    if not clave:
        sys.exit("Falta OPENAI_API_KEY. Usa --sin-ia para probar sin OpenAI.")
    r = requests.post(
        "https://api.openai.com/v1/images/generations",
        headers={"Authorization": f"Bearer {clave}"},
        json={
            "model": os.environ.get("MODELO_IMAGEN") or cfg["modelo_imagen"],
            "prompt": prompt_foto(tema),
            "size": "1024x1536",
            "quality": os.environ.get("CALIDAD_IMAGEN") or cfg["calidad_imagen"],
            "n": 1,
        },
        timeout=400,
    )
    if r.status_code != 200:
        sys.exit(f"OpenAI respondió {r.status_code}: {r.text[:500]}")
    datos = r.json()["data"][0]
    crudo = base64.b64decode(datos["b64_json"]) if datos.get("b64_json") else requests.get(datos["url"], timeout=120).content
    return Image.open(io.BytesIO(crudo)).convert("RGB")


def foto_prueba(cfg: dict) -> Image.Image:
    navy, cian = cfg["c"]["navy"], cfg["c"]["cian"]
    img = Image.new("RGB", (1024, 1536))
    d = ImageDraw.Draw(img)
    for y in range(1536):
        t = y / 1535
        d.line([(0, y), (1024, y)], fill=tuple(int(cian[i] * (1 - t) * 0.7 + navy[i] * (0.3 + t * 0.7)) for i in range(3)))
    return img


# ================================================================ textos
def enlace_whatsapp(cfg: dict, tema: dict) -> str:
    mensaje = f"Hola STC Perú, vi su publicación «{tema['titulo']}» y quiero información sobre {tema['servicio']}."
    return f"https://wa.me/{cfg['whatsapp_numero']}?text={quote(mensaje)}"


def tres_datos(tema: dict) -> list[str]:
    return [f"{s['titulo']}: {s['texto']}" for s in tema["slides"][:3]]


def leyendas(tema: dict, cfg: dict) -> dict:
    etiquetas = " ".join(tema["hashtags"] + ["#STCPerú"])
    numeros = ["1️⃣", "2️⃣", "3️⃣"]
    datos = "\n".join(f"{numeros[i]} {d}" for i, d in enumerate(tres_datos(tema)[:3]))
    cuerpo = f"{tema['gancho']}\n\n{tema['contexto']}\n\n{datos}\n\n{tema['cierre']}\n\n📚 Fuente: {tema['fuente']}"
    facebook = (
        f"{cuerpo}\n\n"
        f"💬 Escríbenos por WhatsApp: {enlace_whatsapp(cfg, tema)}\n"
        f"🌐 {cfg['web']}  ·  📍 {cfg['ciudades']}\n\n{etiquetas}"
    )
    instagram = (
        f"{cuerpo}\n\n"
        f"💬 WhatsApp {cfg['whatsapp']} (enlace directo en nuestro perfil)\n"
        f"🌐 {cfg['web']}  ·  📍 {cfg['ciudades']}\n\n{etiquetas}"
    )
    return {"facebook": facebook, "instagram": instagram}


# ================================================================ calendario
def siguiente_horario(cfg: dict, ocupados: list[datetime]) -> datetime:
    ocupados = [o if o.tzinfo else o.replace(tzinfo=PERU) for o in ocupados]
    desde = max([datetime.now(PERU) + timedelta(hours=12)] + ocupados)
    dia = desde.replace(second=0, microsecond=0)
    for _ in range(0, 24 * 15):
        for semana, hora in cfg["horarios"]:
            h, mi = map(int, hora.split(":"))
            candidato = dia.replace(hour=h, minute=mi)
            if candidato.weekday() == semana and candidato > desde:
                return candidato
        dia = (dia + timedelta(days=1)).replace(hour=0, minute=0)
    raise RuntimeError("No se encontró horario libre")


# ================================================================ flujo
def guardar_imagenes(paginas: list[Image.Image], destino: Path) -> list[str]:
    for viejo in destino.glob("imagen*.jpg"):
        viejo.unlink()
    rutas = []
    for i, pagina in enumerate(paginas, start=1):
        nombre = "imagen.jpg" if len(paginas) == 1 else f"imagen-{i}.jpg"
        pagina.save(destino / nombre, "JPEG", quality=90, optimize=True, progressive=True)
        rutas.append(f"posts/{destino.name}/{nombre}")
    return rutas


def vertical(pagina: Image.Image, foto: Image.Image, cfg: dict) -> Image.Image:
    """Versión 9:16 (1080x1920) para historias y reels: diseño centrado sobre la foto desenfocada."""
    c = cfg["c"]
    lienzo = cubrir(foto, 1080, 1920).filter(ImageFilter.GaussianBlur(28))
    velo(lienzo, c["navy"], 150)
    escala = 0.9
    diseno = pagina.resize((int(W * escala), int(H * escala)), Image.LANCZOS)
    diseno, mascara = redondear(diseno, 36)
    x, y = (1080 - diseno.width) // 2, 250
    lienzo.paste(diseno, (x, y), mascara)
    d = ImageDraw.Draw(lienzo)
    d.text((540, y + diseno.height + 60), f"WhatsApp {cfg['whatsapp']}  ·  {cfg['web']}",
           font=figtree(34, "Bold"), fill=BLANCO, anchor="ma")
    return lienzo


def crear_reel(cuadros: list[Image.Image], destino: Path) -> None:
    """Video vertical con zoom lento sobre cada cuadro (sin música: se puede añadir en la app)."""
    segundos = 7.0 if len(cuadros) == 1 else 3.2
    fps = 30
    with tempfile.TemporaryDirectory() as tmp:
        clips = []
        for i, cuadro in enumerate(cuadros):
            ruta = Path(tmp) / f"c{i}.jpg"
            cuadro.save(ruta, "JPEG", quality=92)
            clip = Path(tmp) / f"c{i}.mp4"
            n = int(segundos * fps)
            filtro = (f"scale=2160:-1,zoompan=z='min(zoom+0.0007,1.08)':x='iw/2-(iw/zoom/2)':"
                      f"y='ih/2-(ih/zoom/2)':d={n}:s=1080x1920:fps={fps},format=yuv420p")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(ruta), "-vf", filtro,
                            "-t", str(segundos), "-c:v", "libx264", "-preset", "medium", "-crf", "21", str(clip)],
                           check=True)
            clips.append(clip)
        lista = Path(tmp) / "lista.txt"
        lista.write_text("".join(f"file '{c}'\n" for c in clips))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lista),
                        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-shortest",
                        "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-pix_fmt", "yuv420p", "-r", str(fps),
                        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(destino)], check=True)


def producir(foto: Image.Image, tema: dict, cfg: dict, destino: Path) -> dict:
    paginas = armar(foto, tema, cfg)
    verticales = [vertical(p, foto, cfg) for p in paginas]
    verticales[0].save(destino / "historia.jpg", "JPEG", quality=90, optimize=True, progressive=True)
    crear_reel(verticales, destino / "reel.mp4")
    return {
        "imagenes": guardar_imagenes(paginas, destino),
        "historia": f"posts/{destino.name}/historia.jpg",
        "reel": f"posts/{destino.name}/reel.mp4",
    }


def resumen(post: dict) -> dict:
    claves = ("id", "tema", "formato", "titulo", "categoria", "imagenes", "historia", "reel", "estado", "programado",
              "creado", "publicado")
    return {k: post.get(k) for k in claves}


def generar(tema: dict, cfg: dict, indice: list[dict], sin_ia: bool) -> dict:
    ahora = datetime.now(PERU)
    carpeta = f"{ahora:%Y-%m-%d}-{tema['id']}"
    destino = POSTS / carpeta
    destino.mkdir(parents=True, exist_ok=True)

    if (destino / "foto.jpg").exists() and not sin_ia:
        foto = Image.open(destino / "foto.jpg").convert("RGB")   # reutiliza la foto ya pagada
    else:
        foto = foto_prueba(cfg) if sin_ia else foto_openai(tema, cfg)
        foto.save(destino / "foto.jpg", "JPEG", quality=88)
    ocupados = [datetime.fromisoformat(p["programado"]) for p in indice if p.get("programado")]
    post = {
        "id": carpeta,
        "tema": tema["id"],
        "formato": tema["formato"],
        "categoria": tema["categoria"],
        "titulo": tema["titulo"],
        **producir(foto, tema, cfg, destino),
        "leyenda": leyendas(tema, cfg),
        "whatsapp": enlace_whatsapp(cfg, tema),
        "datos": tres_datos(tema)[:3],
        "fuente": tema["fuente"],
        "fuentes": tema.get("fuentes", []),
        "estado": "borrador",
        "programado": siguiente_horario(cfg, ocupados).isoformat(timespec="minutes"),
        "creado": ahora.isoformat(timespec="seconds"),
        "prueba": sin_ia,
        "publicado": {},
    }
    guardar_json(destino / "post.json", post)
    indice.append(resumen(post))
    return post


def redisenar(id_post: str, temas: list[dict], cfg: dict, indice: list[dict]) -> dict:
    destino = POSTS / id_post
    post = leer_json(destino / "post.json", None) or sys.exit(f"No existe {id_post}")
    tema = next(t for t in temas if t["id"] == post["tema"])
    foto = Image.open(destino / "foto.jpg").convert("RGB")
    post.update(**producir(foto, tema, cfg, destino),
                leyenda=leyendas(tema, cfg), whatsapp=enlace_whatsapp(cfg, tema),
                datos=tres_datos(tema)[:3], fuente=tema["fuente"], fuentes=tema.get("fuentes", []),
                titulo=tema["titulo"], formato=tema["formato"])
    guardar_json(destino / "post.json", post)
    for i, p in enumerate(indice):
        if p["id"] == id_post:
            indice[i] = resumen(post)
    return post


def main() -> None:
    args = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    args.add_argument("--cantidad", type=int, default=1)
    args.add_argument("--tema")
    args.add_argument("--redisenar", nargs="+", metavar="ID")
    args.add_argument("--sin-ia", action="store_true")
    op = args.parse_args()

    cfg = leer_json(CONFIG, {})
    cfg["c"] = {k: rgb(v) for k, v in cfg["colores"].items()}
    temas, indice = leer_json(TEMAS, []), leer_json(INDICE, [])

    if op.redisenar:
        for id_post in op.redisenar:
            print("Rediseñada:", redisenar(id_post, temas, cfg, indice)["imagenes"])
        guardar_json(INDICE, indice)
        return

    usados = {p["tema"] for p in indice}
    creados = []
    for _ in range(1 if op.tema else op.cantidad):
        if op.tema:
            tema = next((t for t in temas if t["id"] == op.tema), None) or sys.exit(f"No existe el tema '{op.tema}'.")
        else:
            tema = next((t for t in temas if t["id"] not in usados), None)
        if not tema:
            print("::warning::No quedan temas nuevos en contenido/temas.json. Agrega más.")
            break
        creados.append(generar(tema, cfg, indice, op.sin_ia))
        usados.add(tema["id"])
        guardar_json(INDICE, indice)
        print(f"Creada: {creados[-1]['id']} → {creados[-1]['programado']}")

    if not creados and not op.tema:
        sys.exit(1)
    salida = os.environ.get("GITHUB_OUTPUT")
    if salida:
        with open(salida, "a", encoding="utf-8") as f:
            f.write(f"creados={len(creados)}\ntitulos={' | '.join(p['titulo'] for p in creados)}\n")


if __name__ == "__main__":
    main()
