#!/usr/bin/env python3
"""Convierte videos propios (por ejemplo, de TikTok) en reels para Facebook e Instagram.

Lee contenido/videos.json y, para cada video que aún no esté en posts/, toma el
archivo de la carpeta indicada (nombre = ID de TikTok + .mp4), lo re-codifica en
el formato que piden Meta (H.264 + AAC, 9:16, inicio rápido), extrae una portada
y crea la publicación en estado «borrador» con su fecha programada.

Uso:
  python scripts/importar_videos.py --origen RUTA_DE_LOS_MP4
"""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

RAIZ = Path(__file__).resolve().parent.parent
VIDEOS = RAIZ / "contenido" / "videos.json"
CONFIG = RAIZ / "contenido" / "config.json"
INDICE = RAIZ / "posts" / "index.json"
PERU = timezone(timedelta(hours=-5))


def leer(ruta: Path, defecto=None):
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else defecto


def guardar(ruta: Path, datos) -> None:
    ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def leyendas(v: dict, cfg: dict) -> dict:
    mensaje = f"Hola STC Perú, vi su video «{v['titulo']}» y quiero información sobre {v['servicio']}."
    enlace = f"https://wa.me/{cfg['whatsapp_numero']}?text={quote(mensaje)}"
    zona = "📍 Atendemos en todo el Perú" if v["alcance"] == "nacional" else f"📍 {cfg['ciudades']}"
    etiquetas = " ".join(v["hashtags"] + ["#STCPerú"])
    cuerpo = f"{v['gancho']}\n\n{v['cuerpo']}\n\n{v['pregunta']}"
    return {
        "facebook": f"{cuerpo}\n\n💬 WhatsApp: {enlace}\n🌐 {cfg['web']}  ·  {zona}\n\n{etiquetas}",
        "instagram": f"{cuerpo}\n\n💬 WhatsApp {cfg['whatsapp']} (enlace en nuestro perfil)\n🌐 {cfg['web']}  ·  {zona}\n\n{etiquetas}",
    }


def convertir(origen: Path, destino: Path) -> None:
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(origen),
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
        "-map", "0:v:0", "-map", "0:a:0?", "-map", "1:a:0", "-shortest",
        "-vf", "scale=w=1080:h=1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=0x0A1B3D,fps=30,format=yuv420p",
        "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart", str(destino),
    ], check=True)


def tiene_audio(origen: Path) -> bool:
    salida = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
                             "-of", "csv=p=0", str(origen)], capture_output=True, text=True).stdout
    return bool(salida.strip())


def main() -> None:
    args = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    args.add_argument("--origen", required=True, type=Path)
    op = args.parse_args()

    cfg, indice = leer(CONFIG), leer(INDICE, [])
    existentes = {p["tema"] for p in indice}
    for v in leer(VIDEOS, []):
        tema = f"video-{v['slug']}"
        if tema in existentes:
            continue
        archivo = op.origen / f"{v['tiktok']}.mp4"
        if not archivo.exists():
            print(f"Falta {archivo.name}, se omite.")
            continue
        carpeta = f"{datetime.now(PERU):%Y-%m-%d}-{tema}"
        destino = RAIZ / "posts" / carpeta
        destino.mkdir(parents=True, exist_ok=True)
        if tiene_audio(archivo):
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(archivo),
                            "-vf", "scale=w=1080:h=1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=0x0A1B3D,fps=30,format=yuv420p",
                            "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-c:a", "aac", "-b:a", "128k",
                            "-movflags", "+faststart", str(destino / "reel.mp4")], check=True)
        else:
            convertir(archivo, destino / "reel.mp4")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "1", "-i", str(destino / "reel.mp4"),
                        "-frames:v", "1", "-q:v", "3", str(destino / "portada.jpg")], check=True)
        post = {
            "id": carpeta, "tema": tema, "tipo": "video", "formato": "video", "categoria": v["categoria"],
            "titulo": v["titulo"], "imagenes": [], "historia": None,
            "reel": f"posts/{carpeta}/reel.mp4", "portada": f"posts/{carpeta}/portada.jpg",
            "leyenda": leyendas(v, cfg), "origen": f"TikTok {v['tiktok']}", "alcance": v["alcance"],
            "estado": "borrador", "programado": f"{v['programado']}-05:00",
            "creado": datetime.now(PERU).isoformat(timespec="seconds"), "prueba": False, "publicado": {},
        }
        guardar(destino / "post.json", post)
        indice.append({k: post.get(k) for k in ("id", "tema", "tipo", "formato", "titulo", "categoria", "imagenes",
                                                 "historia", "reel", "portada", "estado", "programado", "creado",
                                                 "publicado")})
        guardar(INDICE, indice)
        print(f"Importado: {carpeta} → {post['programado']}")


if __name__ == "__main__":
    main()
