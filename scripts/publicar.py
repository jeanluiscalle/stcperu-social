#!/usr/bin/env python3
"""Publica en Facebook e Instagram las publicaciones aprobadas cuya hora ya llegó.

Solo publica posts con estado «aprobado» y fecha «programado» vencida (con 20
minutos de margen, porque GitHub puede adelantar o retrasar los horarios).
Soporta imagen única y carrusel. La imagen debe estar visible en internet:
se usa GitHub Pages y, si aún no responde, el archivo directo del repositorio.

Variables de entorno (GitHub → Settings → Secrets and variables → Actions):
  META_PAGE_TOKEN   token de la Página o de un usuario que la administra (secreto)
  FB_PAGE_ID        opcional; por defecto el de contenido/config.json
  IG_USER_ID        opcional; por defecto el de contenido/config.json
  REDES             opcional, por defecto todas: facebook, instagram,
                    facebook_historia, instagram_historia, facebook_reel, instagram_reel
  GRAPH_VERSION     opcional, por defecto "v23.0"

Uso:
  python scripts/publicar.py              # publica lo que toca
  python scripts/publicar.py --id ID      # fuerza una publicación concreta (aprobada o no)
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
MARGEN = timedelta(minutes=20)


def leer_json(ruta: Path):
    return json.loads(ruta.read_text(encoding="utf-8"))


def guardar_json(ruta: Path, datos) -> None:
    ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class Meta:
    def __init__(self, token: str, version: str, token_en_parametro: bool = False):
        self.version = version
        self.base = f"https://graph.facebook.com/{version}"
        # El token va en la cabecera; el de Página derivado va como parámetro para que
        # tenga prioridad aunque un proxy añada su propia cabecera Authorization.
        self.cabeceras = {} if token_en_parametro else {"Authorization": f"Bearer {token}"}
        self.extra = {"access_token": token} if token_en_parametro else {}

    def post(self, ruta: str, **datos) -> dict:
        r = requests.post(f"{self.base}/{ruta}", data={**datos, **self.extra}, headers=self.cabeceras, timeout=120)
        return self._revisar(r)

    def get(self, ruta: str, **params) -> dict:
        r = requests.get(f"{self.base}/{ruta}", params={**params, **self.extra}, headers=self.cabeceras, timeout=60)
        return self._revisar(r)

    def de_pagina(self, pagina: str) -> "Meta":
        """Cliente con el token de la Página (sirve tanto con token de usuario como de página)."""
        token = self.get(pagina, fields="access_token").get("access_token")
        return Meta(token, self.version, token_en_parametro=True) if token else self

    @staticmethod
    def _revisar(r: requests.Response) -> dict:
        datos = r.json() if r.content else {}
        if r.status_code != 200 or "error" in datos:
            error = datos.get("error", {})
            raise RuntimeError(f"Meta {r.status_code}: {error.get('message', r.text[:300])}")
        return datos


# ---------------------------------------------------------------- redes
def publicar_facebook(meta: Meta, pagina: str, urls: list[str], texto: str) -> dict:
    cliente = meta.de_pagina(pagina)
    if len(urls) == 1:
        r = cliente.post(f"{pagina}/photos", url=urls[0], caption=texto, published="true")
        ident = r.get("post_id") or r["id"]
    else:
        fotos = [cliente.post(f"{pagina}/photos", url=u, published="false")["id"] for u in urls]
        adjuntos = {f"attached_media[{i}]": json.dumps({"media_fbid": f}) for i, f in enumerate(fotos)}
        ident = cliente.post(f"{pagina}/feed", message=texto, **adjuntos)["id"]
    return {"id": ident, "url": f"https://www.facebook.com/{ident}"}


def esperar_contenedor(meta: Meta, contenedor: str, intentos: int = 36) -> None:
    for _ in range(intentos):
        estado = meta.get(contenedor, fields="status_code").get("status_code")
        if estado == "FINISHED":
            return
        if estado in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram no pudo procesar la imagen (estado {estado}).")
        time.sleep(5)
    raise RuntimeError("Instagram tardó demasiado en procesar la imagen.")


def publicar_instagram(meta: Meta, cuenta: str, urls: list[str], texto: str) -> dict:
    if len(urls) == 1:
        contenedor = meta.post(f"{cuenta}/media", image_url=urls[0], caption=texto)["id"]
    else:
        hijos = [meta.post(f"{cuenta}/media", image_url=u, is_carousel_item="true")["id"] for u in urls]
        for hijo in hijos:
            esperar_contenedor(meta, hijo)
        contenedor = meta.post(f"{cuenta}/media", media_type="CAROUSEL", children=",".join(hijos), caption=texto)["id"]
    esperar_contenedor(meta, contenedor)
    ident = meta.post(f"{cuenta}/media_publish", creation_id=contenedor)["id"]
    try:
        url = meta.get(ident, fields="permalink").get("permalink")
    except RuntimeError:
        url = None
    return {"id": ident, "url": url}


def publicar_ig_historia(meta: Meta, cuenta: str, url: str, _texto: str) -> dict:
    contenedor = meta.post(f"{cuenta}/media", media_type="STORIES", image_url=url)["id"]
    esperar_contenedor(meta, contenedor)
    return {"id": meta.post(f"{cuenta}/media_publish", creation_id=contenedor)["id"], "url": None}


def publicar_ig_reel(meta: Meta, cuenta: str, url: str, texto: str, al_feed: bool = False) -> dict:
    # Para carruseles el reel va solo a la pestaña Reels (el post del feed ya existe);
    # para publicaciones de video, el reel también aparece en el feed.
    contenedor = meta.post(f"{cuenta}/media", media_type="REELS", video_url=url, caption=texto,
                           share_to_feed="true" if al_feed else "false")["id"]
    esperar_contenedor(meta, contenedor, intentos=72)
    ident = meta.post(f"{cuenta}/media_publish", creation_id=contenedor)["id"]
    try:
        enlace = meta.get(ident, fields="permalink").get("permalink")
    except RuntimeError:
        enlace = None
    return {"id": ident, "url": enlace}


def publicar_fb_historia(meta: Meta, pagina: str, url: str, _texto: str) -> dict:
    cliente = meta.de_pagina(pagina)
    foto = cliente.post(f"{pagina}/photos", url=url, published="false")["id"]
    return {"id": cliente.post(f"{pagina}/photo_stories", photo_id=foto).get("post_id", foto), "url": None}


def publicar_fb_reel(meta: Meta, pagina: str, url: str, texto: str) -> dict:
    cliente = meta.de_pagina(pagina)
    inicio = cliente.post(f"{pagina}/video_reels", upload_phase="start")
    token = cliente.extra.get("access_token") or cliente.cabeceras.get("Authorization", "").replace("Bearer ", "")
    r = requests.post(inicio["upload_url"], headers={"Authorization": f"OAuth {token}", "file_url": url}, timeout=300)
    Meta._revisar(r)
    cliente.post(f"{pagina}/video_reels", upload_phase="finish", video_id=inicio["video_id"],
                 video_state="PUBLISHED", description=texto)
    return {"id": inicio["video_id"], "url": f"https://www.facebook.com/reel/{inicio['video_id']}"}


# ---------------------------------------------------------------- imágenes
def imagen_visible(url: str) -> bool:
    try:
        r = requests.head(url, timeout=30, allow_redirects=True)
        tipo = r.headers.get("content-type", "")
        return r.status_code == 200 and (tipo.startswith("image/jpeg") or tipo.startswith("video/mp4"))
    except requests.RequestException:
        return False


def url_imagen(base: str, ruta: str) -> str:
    principal = f"{base}/{ruta}"
    if imagen_visible(principal):
        return principal
    repo = os.environ.get("GITHUB_REPOSITORY", "jeanluiscalle/stcperu-social")
    respaldo = f"https://raw.githubusercontent.com/{repo}/main/{ruta}"
    if imagen_visible(respaldo):
        return respaldo
    raise RuntimeError(f"La imagen {ruta} no está visible en internet todavía.")


# ---------------------------------------------------------------- flujo
def pendientes(indice: list[dict], redes: list[str], forzado: str | None) -> list[dict]:
    if forzado:
        return [p for p in indice if p["id"] == forzado]
    ahora = datetime.now(PERU)
    return [
        p for p in sorted(indice, key=lambda p: p.get("programado") or "")
        if p.get("estado") == "aprobado"
        and p.get("programado") and datetime.fromisoformat(p["programado"]) <= ahora + MARGEN
        and p.get("estado") != "publicado"
    ]


def publicar_post(entrada: dict, cfg: dict, redes: list[str], meta: Meta | None, simular: bool) -> list[str]:
    ruta = RAIZ / "posts" / entrada["id"] / "post.json"
    post = leer_json(ruta)
    base = (os.environ.get("BASE_URL") or cfg["base_url"]).rstrip("/")
    urls = [url_imagen(base, r) for r in post["imagenes"]]
    print(f"\n▶ {post['titulo']} ({len(urls)} imagen/es, programado {post.get('programado')})")
    if simular:
        print(post["leyenda"]["instagram"])
        return []

    pagina = os.environ.get("FB_PAGE_ID") or cfg.get("fb_page_id")
    cuenta = os.environ.get("IG_USER_ID") or cfg.get("ig_user_id")
    historia = post.get("historia")
    reel = post.get("reel")
    es_video = post.get("tipo") == "video"
    destinos = {
        "facebook": (pagina, publicar_facebook, urls or None, "facebook"),
        "instagram": (cuenta, publicar_instagram, urls or None, "instagram"),
        "facebook_historia": (pagina, publicar_fb_historia, historia, "facebook"),
        "instagram_historia": (cuenta, publicar_ig_historia, historia, "instagram"),
        "facebook_reel": (pagina, publicar_fb_reel, reel, "facebook"),
        "instagram_reel": (cuenta, (lambda m, c, u, t: publicar_ig_reel(m, c, u, t, al_feed=True)) if es_video
                           else publicar_ig_reel, reel, "instagram"),
    }
    post.setdefault("publicado", {})
    fallos = []
    for red in redes:
        if post["publicado"].get(red) or red not in destinos:
            continue
        ident, funcion, recurso, leyenda = destinos[red]
        if recurso is None:
            continue                          # publicación antigua sin historia o reel
        try:
            if isinstance(recurso, str):
                recurso = url_imagen(base, recurso)
            resultado = funcion(meta, ident, recurso, post["leyenda"][leyenda])
        except (RuntimeError, requests.RequestException) as error:
            fallos.append(f"{post['id']} · {red}: {error}")
            continue
        resultado["fecha"] = datetime.now(PERU).isoformat(timespec="seconds")
        post["publicado"][red] = resultado
        entrada.setdefault("publicado", {})[red] = resultado
        print(f"  Publicado en {red}: {resultado['url'] or resultado['id']}")

    if all(post["publicado"].get(r) or destinos.get(r, (0, 0, 0))[2] is None for r in redes):
        post["estado"] = entrada["estado"] = "publicado"
    guardar_json(ruta, post)
    return fallos


def verificar_conexion(cfg: dict) -> None:
    """Prueba el token de Meta y el acceso a la Página e Instagram, sin publicar nada."""
    token = os.environ.get("META_PAGE_TOKEN")
    if not token:
        print("::warning::META_PAGE_TOKEN no está configurado.")
        return
    meta = Meta(token, os.environ.get("GRAPH_VERSION", "v23.0"))
    pagina = os.environ.get("FB_PAGE_ID") or cfg.get("fb_page_id")
    cuenta = os.environ.get("IG_USER_ID") or cfg.get("ig_user_id")
    try:
        nombre = meta.de_pagina(pagina).get(pagina, fields="name")["name"]
        usuario = meta.get(cuenta, fields="username")["username"]
        cuota = meta.get(f"{cuenta}/content_publishing_limit", fields="quota_usage")["data"][0]["quota_usage"]
    except (RuntimeError, KeyError, IndexError) as error:
        sys.exit(f"Conexión con Meta FALLÓ: {error}")
    print(f"✅ Conexión con Meta correcta: Página «{nombre}» e Instagram @{usuario} "
          f"({cuota} publicaciones por API en las últimas 24 h).")


def main() -> None:
    args = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    args.add_argument("--simular", action="store_true")
    args.add_argument("--id")
    op = args.parse_args()

    cfg = leer_json(CONFIG)
    todas = "facebook,instagram,facebook_historia,instagram_historia,facebook_reel,instagram_reel"
    redes = [r.strip() for r in (os.environ.get("REDES") or todas).split(",") if r.strip()]
    indice = leer_json(INDICE) if INDICE.exists() else []
    cola = pendientes(indice, redes, op.id)
    if op.simular:
        verificar_conexion(cfg)
    if not cola:
        print("::notice::No hay publicaciones aprobadas para esta hora.")
        return

    meta = None
    if not op.simular:
        token = os.environ.get("META_PAGE_TOKEN")
        if not token:
            print("::warning::Falta el secreto META_PAGE_TOKEN; no se publicó nada.")
            return
        meta = Meta(token, os.environ.get("GRAPH_VERSION", "v23.0"))

    fallos = []
    for entrada in cola:
        try:
            fallos += publicar_post(entrada, cfg, redes, meta, op.simular)
        except RuntimeError as error:
            fallos.append(f"{entrada['id']}: {error}")
    guardar_json(INDICE, indice)
    if fallos:
        sys.exit("Errores:\n- " + "\n- ".join(fallos))


if __name__ == "__main__":
    main()
