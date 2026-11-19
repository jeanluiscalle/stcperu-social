# STC Perú Social

Publicaciones automáticas para Facebook e Instagram de [STC Perú](https://stcperu.com), más un blog público con todos los consejos.

**Blog:** https://jeanluiscalle.github.io/stcperu-social/

## Cómo funciona

1. **Domingo 6:13 p.m.** — el workflow *Preparar publicaciones* toma los 3 siguientes temas de `contenido/temas.json`, pide a OpenAI una foto (sin texto) y le pone encima el título y los consejos con las fuentes de la marca.
2. Se abre un **Pull Request** para que revises las imágenes. Si te gustan, pulsa **Merge**.
3. **Martes 12:30 p.m., jueves 7:00 p.m. y sábado 10:00 a.m.** — el workflow *Publicar en redes* sube la siguiente publicación aprobada a Facebook e Instagram y la registra.
4. El blog (GitHub Pages) se actualiza solo.

Todas las horas son de Perú. Se cambian en el bloque `cron` de cada workflow (en UTC, Perú = UTC−5).

## Configuración (una sola vez)

En **Settings** del repositorio:

| Dónde | Qué |
|---|---|
| Pages → Build and deployment → Source | **GitHub Actions** |
| Actions → General → Workflow permissions | **Read and write** y marcar **Allow GitHub Actions to create and approve pull requests** |
| Secrets and variables → Actions → **Secrets** | `OPENAI_API_KEY`, `META_PAGE_TOKEN` |

Variables opcionales:

| Variable | Para qué | Por defecto |
|---|---|---|
| `FB_PAGE_ID` / `IG_USER_ID` | otra Página o cuenta | los de `contenido/config.json` |
| `APROBACION_MANUAL` | `false` = se publican sin revisión | revisión con PR |
| `REDES` | `facebook`, `instagram` o ambas | `facebook,instagram` |
| `MODELO_IMAGEN` / `CALIDAD_IMAGEN` | modelo y calidad de OpenAI | `gpt-image-1.5` / `medium` |
| `GRAPH_VERSION` | versión de la API de Meta | `v23.0` |

## Agregar temas

Edita `contenido/temas.json`. Cada tema lleva: `id` (sin tildes ni espacios), `categoria`, `titulo`, 3 `puntos`, `escena` (qué debe mostrar la foto), `servicio` y `hashtags`.

## Uso manual

```bash
pip install -r requirements.txt
python scripts/generar.py --sin-ia          # prueba de diseño sin gastar en OpenAI
OPENAI_API_KEY=... python scripts/generar.py --cantidad 3
python scripts/publicar.py --simular        # ver qué se publicaría
```

Desde GitHub: pestaña **Actions** → elige el workflow → **Run workflow**.

## Costos

- Meta Graph API: gratis.
- OpenAI: unos US$ 0.03–0.07 por imagen en calidad media (≈ US$ 1 al mes con 12 publicaciones).
- GitHub Actions y Pages: gratis en repositorios públicos.

Fuentes: Anton y Figtree (SIL Open Font License).
