#!/usr/bin/env python3
"""Genera las próximas publicaciones de STC Perú.

Toma el siguiente tema sin usar de contenido/temas.json, pide a OpenAI una
imagen ilustrativa SIN texto y le superpone el título y los consejos con las
fuentes de la marca (así el texto nunca sale con faltas de ortografía).

Uso:
  python scripts/generar.py                 # 1 publicación
  python scripts/generar.py --cantidad 3    # 3 publicaciones
  python scripts/generar.py --tema starlink # un tema concreto
  python scripts/generar.py --sin-ia        # fondo de prueba, sin gastar en OpenAI

Requiere la variable de entorno OPENAI_API_KEY (salvo con --sin-ia).
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

RAIZ = Path(__file__).resolve().parent.parent
TEMAS = RAIZ / "contenido" / "temas.json"
CONFIG = RAIZ / "contenido" / "config.json"
POSTS = RAIZ / "posts"
INDICE = POSTS / "index.json"
FUENTES = RAIZ / "assets" / "fonts"

ANCHO, ALTO = 1080, 1350          # formato 4:5, el que más ocupa en el feed
ALTO_FOTO = 760
MARGEN = 64
ALTO_PIE = 112
PERU = timezone(timedelta(hours=-5))


def leer_json(ruta: Path, defecto):
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else defecto


def guardar_json(ruta: Path, datos) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def hex_rgb(valor: str) -> tuple[int, int, int]:
    valor = valor.lstrip("#")
    return tuple(int(valor[i:i + 2], 16) for i in (0, 2, 4))


def fuente_titulo(tamano: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FUENTES / "Anton-Regular.ttf"), tamano)


def fuente_texto(tamano: int, peso: str = "SemiBold") -> ImageFont.FreeTypeFont:
    fuente = ImageFont.truetype(str(FUENTES / "Figtree-VF.ttf"), tamano)
    fuente.set_variation_by_name(peso)
    return fuente


# ---------------------------------------------------------------- imagen IA
def prompt_imagen(tema: dict) -> str:
    return (
        f"Fotografía publicitaria realista y profesional de {tema['escena']}. "
        "Estilo limpio y moderno, iluminación de estudio suave, colores azul marino y cian como acentos, "
        "profundidad de campo, composición con espacio libre en la parte inferior. "
        "IMPORTANTE: sin texto, sin letras, sin números, sin logotipos ni marcas visibles."
    )


def imagen_openai(tema: dict, config: dict) -> Image.Image:
    clave = os.environ.get("OPENAI_API_KEY")
    if not clave:
        sys.exit("Falta OPENAI_API_KEY. Usa --sin-ia para probar sin OpenAI.")
    respuesta = requests.post(
        "https://api.openai.com/v1/images/generations",
        headers={"Authorization": f"Bearer {clave}"},
        json={
            "model": os.environ.get("MODELO_IMAGEN") or config["modelo_imagen"],
            "prompt": prompt_imagen(tema),
            "size": "1536x1024",
            "quality": os.environ.get("CALIDAD_IMAGEN") or config["calidad_imagen"],
            "n": 1,
        },
        timeout=300,
    )
    if respuesta.status_code != 200:
        sys.exit(f"OpenAI respondió {respuesta.status_code}: {respuesta.text[:500]}")
    datos = respuesta.json()["data"][0]
    if datos.get("b64_json"):
        crudo = base64.b64decode(datos["b64_json"])
    else:
        crudo = requests.get(datos["url"], timeout=120).content
    return Image.open(io.BytesIO(crudo)).convert("RGB")


def imagen_prueba(config: dict) -> Image.Image:
    navy, cian = hex_rgb(config["colores"]["navy"]), hex_rgb(config["colores"]["cian"])
    fondo = Image.new("RGB", (1536, 1024), navy)
    capa = ImageDraw.Draw(fondo)
    for x in range(1536):
        t = x / 1535
        capa.line([(x, 0), (x, 1024)], fill=tuple(int(navy[i] + (cian[i] - navy[i]) * t * 0.6) for i in range(3)))
    return fondo


# ---------------------------------------------------------------- diseño
def ajustar(img: Image.Image, ancho: int, alto: int) -> Image.Image:
    escala = max(ancho / img.width, alto / img.height)
    img = img.resize((round(img.width * escala), round(img.height * escala)), Image.LANCZOS)
    x, y = (img.width - ancho) // 2, (img.height - alto) // 2
    return img.crop((x, y, x + ancho, y + alto))


def partir(texto: str, fuente, ancho_max: int, dibujo: ImageDraw.ImageDraw) -> list[str]:
    lineas, actual = [], ""
    for palabra in texto.split():
        prueba = f"{actual} {palabra}".strip()
        if dibujo.textlength(prueba, font=fuente) <= ancho_max:
            actual = prueba
        else:
            if actual:
                lineas.append(actual)
            actual = palabra
    if actual:
        lineas.append(actual)
    return lineas


def componer(foto: Image.Image, tema: dict, config: dict) -> Image.Image:
    colores = {k: hex_rgb(v) for k, v in config["colores"].items()}
    lienzo = Image.new("RGB", (ANCHO, ALTO), colores["navy"])
    lienzo.paste(ajustar(foto, ANCHO, ALTO_FOTO), (0, 0))

    # Degradado de la foto hacia el azul marino para leer bien el texto.
    degradado = Image.new("L", (1, ALTO_FOTO))
    for y in range(ALTO_FOTO):
        inicio = ALTO_FOTO * 0.45
        degradado.putpixel((0, y), 0 if y < inicio else int(255 * ((y - inicio) / (ALTO_FOTO - inicio)) ** 1.4))
    capa_navy = Image.new("RGB", (ANCHO, ALTO_FOTO), colores["navy"])
    lienzo.paste(capa_navy, (0, 0), degradado.resize((ANCHO, ALTO_FOTO)))

    dibujo = ImageDraw.Draw(lienzo)
    ancho_texto = ANCHO - 2 * MARGEN

    # Etiqueta de categoría
    f_cat = fuente_texto(28, "Bold")
    etiqueta = tema["categoria"].upper()
    w = dibujo.textlength(etiqueta, font=f_cat)
    dibujo.rounded_rectangle((MARGEN, MARGEN, MARGEN + w + 40, MARGEN + 52), radius=26, fill=colores["cian"])
    dibujo.text((MARGEN + 20, MARGEN + 26), etiqueta, font=f_cat, fill=colores["navy"], anchor="lm")

    # Bloque de texto: se reduce la letra hasta que todo entre.
    tope = ALTO - ALTO_PIE - 48
    for t_titulo, t_punto in ((84, 38), (76, 36), (68, 34), (62, 32), (56, 30)):
        f_titulo, f_punto = fuente_titulo(t_titulo), fuente_texto(t_punto, "Medium")
        l_titulo = partir(tema["titulo"].upper(), f_titulo, ancho_texto, dibujo)
        sangria = 84
        l_puntos = [partir(p, f_punto, ancho_texto - sangria, dibujo) for p in tema["puntos"]]
        alto_titulo = len(l_titulo) * int(t_titulo * 1.12)
        alto_puntos = sum(len(l) * int(t_punto * 1.3) + 26 for l in l_puntos)
        alto_total = 14 + 12 + alto_titulo + 36 + alto_puntos
        if alto_total <= tope - 580:
            break
    y = tope - alto_total

    dibujo.rectangle((MARGEN, y, MARGEN + 96, y + 10), fill=colores["cian"])
    y += 14 + 12
    for linea in l_titulo:
        dibujo.text((MARGEN, y), linea, font=f_titulo, fill=(255, 255, 255))
        y += int(t_titulo * 1.12)
    y += 36

    f_num = fuente_titulo(34)
    for numero, lineas in enumerate(l_puntos, start=1):
        cy = y + int(t_punto * 0.65)
        dibujo.ellipse((MARGEN, cy - 26, MARGEN + 52, cy + 26), fill=colores["cian"])
        dibujo.text((MARGEN + 26, cy), str(numero), font=f_num, fill=colores["navy"], anchor="mm")
        for linea in lineas:
            dibujo.text((MARGEN + sangria, y), linea, font=f_punto, fill=(232, 238, 250))
            y += int(t_punto * 1.3)
        y += 26

    # Pie de marca
    pie_y = ALTO - ALTO_PIE
    dibujo.rectangle((0, pie_y, ANCHO, ALTO), fill=(15, 37, 82))
    dibujo.rectangle((0, pie_y, ANCHO, pie_y + 4), fill=colores["cian"])
    centro = pie_y + ALTO_PIE // 2 + 2
    marca = config["marca"].upper()
    f_marca = fuente_titulo(46)
    dibujo.text((MARGEN, centro), marca, font=f_marca, fill=colores["cian"], anchor="lm")
    x_sub = MARGEN + dibujo.textlength(marca, font=f_marca) + 22
    f_sub = fuente_texto(24, "Medium")
    dibujo.text((x_sub, centro - 15), "Servicio técnico", font=f_sub, fill=(200, 212, 235), anchor="lm")
    dibujo.text((x_sub, centro + 15), config["ciudades"], font=f_sub, fill=(200, 212, 235), anchor="lm")
    f_wa = fuente_texto(32, "Bold")
    dibujo.text((ANCHO - MARGEN, centro - 16), f"WhatsApp {config['whatsapp']}", font=f_wa, fill=(255, 255, 255), anchor="rm")
    dibujo.text((ANCHO - MARGEN, centro + 20), config["web"], font=fuente_texto(26, "Medium"), fill=colores["cian"], anchor="rm")
    return lienzo


# ---------------------------------------------------------------- texto
def leyenda(tema: dict, config: dict) -> str:
    puntos = "\n".join(f"{i}. {p}" for i, p in enumerate(tema["puntos"], start=1))
    etiquetas = " ".join(tema["hashtags"] + ["#STCPerú", "#ServicioTécnico"])
    return (
        f"{tema['titulo']}\n\n{puntos}\n\n"
        f"¿Necesitas ayuda? En {config['marca']} te ayudamos con: {tema['servicio']}.\n"
        f"📲 WhatsApp {config['whatsapp']}\n"
        f"🌐 {config['web']}\n"
        f"📍 {config['ciudades']}\n\n"
        f"{etiquetas}"
    )


# ---------------------------------------------------------------- flujo
def siguiente_tema(temas: list[dict], indice: list[dict], forzado: str | None) -> dict | None:
    if forzado:
        return next((t for t in temas if t["id"] == forzado), None) or sys.exit(f"No existe el tema '{forzado}'.")
    usados = {p["tema"] for p in indice}
    return next((t for t in temas if t["id"] not in usados), None)


def generar_una(tema: dict, config: dict, indice: list[dict], sin_ia: bool) -> dict:
    ahora = datetime.now(PERU)
    carpeta = f"{ahora:%Y-%m-%d}-{tema['id']}"
    destino = POSTS / carpeta
    destino.mkdir(parents=True, exist_ok=True)

    foto = imagen_prueba(config) if sin_ia else imagen_openai(tema, config)
    componer(foto, tema, config).save(destino / "imagen.jpg", "JPEG", quality=90, optimize=True, progressive=True)

    post = {
        "id": carpeta,
        "tema": tema["id"],
        "categoria": tema["categoria"],
        "titulo": tema["titulo"],
        "puntos": tema["puntos"],
        "servicio": tema["servicio"],
        "leyenda": leyenda(tema, config),
        "imagen": f"posts/{carpeta}/imagen.jpg",
        "creado": ahora.isoformat(timespec="seconds"),
        "prueba": sin_ia,
        "publicado": {"facebook": None, "instagram": None},
    }
    guardar_json(destino / "post.json", post)
    indice.append({k: post[k] for k in ("id", "tema", "titulo", "categoria", "puntos", "servicio", "imagen", "creado", "prueba", "publicado")})
    return post


def main() -> None:
    args = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    args.add_argument("--cantidad", type=int, default=1)
    args.add_argument("--tema")
    args.add_argument("--sin-ia", action="store_true")
    opciones = args.parse_args()

    config, temas = leer_json(CONFIG, {}), leer_json(TEMAS, [])
    indice = leer_json(INDICE, [])
    creados = []
    for _ in range(1 if opciones.tema else opciones.cantidad):
        tema = siguiente_tema(temas, indice, opciones.tema)
        if not tema:
            print("::warning::No quedan temas nuevos en contenido/temas.json. Agrega más.")
            break
        creados.append(generar_una(tema, config, indice, opciones.sin_ia))
        guardar_json(INDICE, indice)
        print(f"Creada: {creados[-1]['imagen']}")

    if not creados:
        sys.exit(1)
    salida = os.environ.get("GITHUB_OUTPUT")
    if salida:
        with open(salida, "a", encoding="utf-8") as f:
            f.write(f"creados={len(creados)}\n")
            f.write(f"titulos={' | '.join(p['titulo'] for p in creados)}\n")


if __name__ == "__main__":
    main()
