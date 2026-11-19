# STC Perú Social

Publicaciones automáticas para Facebook e Instagram de [STC Perú](https://stcperu.com), más un blog público con todos los consejos.

**Blog:** https://jeanluiscalle.github.io/stcperu-social/

## Cómo funciona

1. **Domingo 6:13 p.m.** — *Preparar publicaciones* toma los siguientes temas de `contenido/temas.json`, pide a OpenAI (gpt-image-2) una foto realista sin texto y la diseña con uno de 5 formatos: **portada, mito vs realidad, carrusel, checklist y dato**. También crea la **historia** (9:16) y un **reel** (MP4).
2. Los borradores aparecen en el **panel**: https://jeanluiscalle.github.io/stcperu-social/panel.html con su fecha programada, los textos de Facebook e Instagram, los 3 datos y la fuente.
3. Se aprueban en **Actions → Aprobar publicaciones** (IDs o «todos»).
4. **Martes 12:30 p.m., jueves 7:00 p.m. y sábado 10:00 a.m.** — *Publicar en redes* sube lo aprobado: feed, historia y reel en Facebook e Instagram.

Cada publicación lleva **exactamente 3 datos** respaldados por una fuente (Epson, Microsoft, HP, CISA…) y un llamado a WhatsApp con mensaje prellenado.

## Configuración (una sola vez)

En **Settings** del repositorio:

| Dónde | Qué |
|---|---|
| Pages → Build and deployment → Source | rama **gh-pages** (ya activo) |
| Actions → General → Workflow permissions | **Read and write** |
| Secrets and variables → Actions → **Secrets** | `OPENAI_API_KEY`, `META_PAGE_TOKEN` |

Variables opcionales:

| Variable | Para qué | Por defecto |
|---|---|---|
| `FB_PAGE_ID` / `IG_USER_ID` | otra Página o cuenta | los de `contenido/config.json` |
| `REDES` | qué publicar | `facebook,instagram,facebook_historia,instagram_historia,facebook_reel,instagram_reel` |
| `MODELO_IMAGEN` / `CALIDAD_IMAGEN` | modelo y calidad de OpenAI | `gpt-image-2` / `medium` |
| `GRAPH_VERSION` | versión de la API de Meta | `v23.0` |

## Agregar temas

Edita `contenido/temas.json`. Cada tema lleva `id` (sin tildes), `formato` (portada, mito, carrusel, checklist o dato), `titulo`, **3 datos** (`puntos` o `slides`), `gancho`, `contexto`, `cierre`, `fuente` con sus `fuentes` (enlaces), `escena` (qué muestra la foto), `servicio` y `hashtags`. Las ideas pendientes están en `contenido/ideas.json`.

## Uso manual

```bash
pip install -r requirements.txt
python scripts/generar.py --sin-ia          # prueba de diseño sin gastar en OpenAI
OPENAI_API_KEY=... python scripts/generar.py --cantidad 3
python scripts/publicar.py --simular        # ver qué se publicaría
python scripts/aprobar.py todos             # aprobar borradores
python scripts/generar.py --redisenar ID    # rehacer el diseño sin pagar otra foto
```

Desde GitHub: pestaña **Actions** → elige el workflow → **Run workflow**.

## Costos

- Meta Graph API: gratis.
- OpenAI: unos US$ 0.03–0.07 por imagen en calidad media (≈ US$ 1 al mes con 12 publicaciones).
- GitHub Actions y Pages: gratis en repositorios públicos.

Fuentes: Anton y Figtree (SIL Open Font License).
