#!/usr/bin/env python3
"""Cambia el estado de publicaciones: aprobar, descartar o volver a borrador.

Uso:
  python scripts/aprobar.py todos                     # aprueba todos los borradores
  python scripts/aprobar.py ID1 ID2 --accion descartar
  python scripts/aprobar.py ID --fecha 2026-11-24T12:30   # además cambia la fecha (hora de Perú)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
INDICE = RAIZ / "posts" / "index.json"
ESTADOS = {"aprobar": "aprobado", "descartar": "descartado", "borrador": "borrador"}


def main() -> None:
    args = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    args.add_argument("ids", nargs="+", help="IDs de publicación o «todos»")
    args.add_argument("--accion", choices=ESTADOS, default="aprobar")
    args.add_argument("--fecha", help="nueva fecha programada, formato AAAA-MM-DDTHH:MM (hora de Perú)")
    op = args.parse_args()

    indice = json.loads(INDICE.read_text(encoding="utf-8"))
    ids = [i.strip() for valor in op.ids for i in valor.replace(",", " ").split() if i.strip()]
    todos = ids == ["todos"]
    cambiados = []
    for entrada in indice:
        if entrada.get("estado") == "publicado":
            continue
        if not (entrada["id"] in ids or (todos and entrada.get("estado") == "borrador")):
            continue
        ruta = RAIZ / "posts" / entrada["id"] / "post.json"
        post = json.loads(ruta.read_text(encoding="utf-8"))
        post["estado"] = entrada["estado"] = ESTADOS[op.accion]
        if op.fecha:
            fecha = op.fecha if len(op.fecha) > 16 else f"{op.fecha}-05:00"   # sin zona → hora de Perú
            post["programado"] = entrada["programado"] = fecha
        ruta.write_text(json.dumps(post, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        cambiados.append(f"{entrada['id']} → {entrada['estado']} ({entrada.get('programado')})")

    if not cambiados:
        sys.exit("No se encontró ninguna publicación con esos IDs (o ya están publicadas).")
    INDICE.write_text(json.dumps(indice, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("\n".join(cambiados))


if __name__ == "__main__":
    main()
