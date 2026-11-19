#!/usr/bin/env python3
"""Publica en Facebook e Instagram la siguiente publicación pendiente.

Toma la publicación más antigua de posts/index.json que aún no se haya
publicado en alguna red y la sube usando la Graph API de Meta. La imagen debe
estar ya visible en GitHub Pages (Instagram la descarga desde esa URL).

Variables de entorno (en GitHub: Settings → Secrets and variables → Actions):
  META_PAGE_TOKEN   token de acceso de la Página (secreto)
  FB_PAGE_ID        ID de la Página de Facebook
  IG_USER_ID        ID de la cuenta profesional de Instagram
  REDES             opcional, por defecto "facebook,instagram"
  GRAPH_VERSION     opcional, por defecto "v23.0"
  BASE_URL          opcional, por defecto el de contenido/config.json

Uso:
  python scripts/publicar.py              # publica la siguiente
  python scripts/publicar.py --simular    # muestra qué haría, sin publicar
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

RAIZ = Path(__file__).resolve().parent.parent
INDICE = RAIZ / "posts" / "index.json"
CONFIG = RAIZ / "contenido" / "config.json"
PERU = timezone(timedelta(hours=-5))


def leer_json(ruta: Path):
    return json.loads(ruta.read_text(encoding="utf-8"))


def guardar_json(ruta: Path, datos) -> None:
    ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class Meta:
    def __init__(self, token: str, version: str):
        self.token, self.base = token, f"https://graph.facebook.com/{version}"

    def post(self, ruta: str, **datos) -> dict:
        r = requests.post(f"{self.base}/{ruta}", data={**datos, "access_token": self.token}, timeout=120)
        return self._revisar(r)

    def get(self, ruta: str, **params) -> dict:
        r = requests.get(f"{self.base}/{ruta}", params={**params, "access_token": self.token}, timeout=60)
        return self._revisar(r)

    @staticmethod
    def _revisar(r: requests.Response) -> dict:
        datos = r.json() if r.content else {}
        if r.status_code != 200 or "error" in datos:
            error = datos.get("error", {})
            raise RuntimeError(f"Meta {r.status_code}: {error.get('message', r.text[:300])}")
        return datos


def publicar_facebook(meta: Meta, pagina: str, url: str, texto: str) -> str:
    respuesta = meta.post(f"{pagina}/photos", url=url, caption=texto, published="true")
    return respuesta.get("post_id") or respuesta["id"]


def publicar_instagram(meta: Meta, cuenta: str, url: str, texto: str) -> str:
    contenedor = meta.post(f"{cuenta}/media", image_url=url, caption=texto)["id"]
    for _ in range(30):                       # Instagram procesa la imagen antes de publicarla
        estado = meta.get(contenedor, fields="status_code").get("status_code")
        if estado == "FINISHED":
            break
        if estado in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram no pudo procesar la imagen (estado {estado}).")
        time.sleep(5)
    return meta.post(f"{cuenta}/media_publish", creation_id=contenedor)["id"]


def imagen_visible(url: str) -> bool:
    try:
        r = requests.head(url, timeout=30, allow_redirects=True)
        return r.status_code == 200 and r.headers.get("content-type", "").startswith("image/jpeg")
    except requests.RequestException:
        return False


def main() -> None:
    args = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    args.add_argument("--simular", action="store_true")
    opciones = args.parse_args()

    config = leer_json(CONFIG)
    redes = [r.strip() for r in os.environ.get("REDES", "facebook,instagram").split(",") if r.strip()]
    indice = leer_json(INDICE) if INDICE.exists() else []
    pendiente = next(
        (p for p in indice if not p.get("prueba") and any(not p["publicado"].get(r) for r in redes)), None
    )
    if not pendiente:
        print("::notice::No hay publicaciones pendientes. Genera nuevas con el workflow «Preparar publicaciones».")
        return

    base = (os.environ.get("BASE_URL") or config["base_url"]).rstrip("/")
    url = f"{base}/{pendiente['imagen']}"
    ruta_post = RAIZ / "posts" / pendiente["id"] / "post.json"
    post = leer_json(ruta_post)
    print(f"Siguiente: {post['titulo']}\nImagen: {url}")

    if opciones.simular:
        print("--- Leyenda ---\n" + post["leyenda"])
        return

    token = os.environ.get("META_PAGE_TOKEN")
    if not token:
        print("::warning::Falta el secreto META_PAGE_TOKEN; no se publicó nada.")
        return
    if not imagen_visible(url):
        sys.exit(f"La imagen aún no está visible en {url}. Revisa que GitHub Pages esté activo y desplegado.")

    meta = Meta(token, os.environ.get("GRAPH_VERSION", "v23.0"))
    destinos = {
        "facebook": (os.environ.get("FB_PAGE_ID"), publicar_facebook),
        "instagram": (os.environ.get("IG_USER_ID"), publicar_instagram),
    }
    fallos = []
    for red in redes:
        if post["publicado"].get(red):
            continue
        cuenta, funcion = destinos[red]
        if not cuenta:
            fallos.append(f"{red}: falta su ID en las variables")
            continue
        try:
            identificador = funcion(meta, cuenta, url, post["leyenda"])
        except (RuntimeError, requests.RequestException) as error:
            fallos.append(f"{red}: {error}")
            continue
        registro = {"id": identificador, "fecha": datetime.now(PERU).isoformat(timespec="seconds")}
        post["publicado"][red] = pendiente["publicado"][red] = registro
        print(f"Publicado en {red}: {identificador}")

    guardar_json(ruta_post, post)
    guardar_json(INDICE, indice)
    if fallos:
        sys.exit("Errores:\n- " + "\n- ".join(fallos))


if __name__ == "__main__":
    main()
