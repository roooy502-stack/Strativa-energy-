# Strativa Energy website

Static HTML site for https://strativaenergy.com.au/. No build step is needed to deploy: commit the files and publish.

## Structure

- `index.html`, `about/`, `services/…`, `insights/…`, `contact/`, `privacy-policy/`, `404.html`: pages (edit directly).
- `partials/`: shared head, header, footer and script blocks. After editing run `python3 scripts/sync_layout.py`.
- `assets/css/site.css`, `assets/js/site.js`: shared styles and behaviour.
- `config/seo_targets.json`: business facts, keywords and the page-to-keyword map.
- `scripts/`: `sync_layout.py`, `build_sitemap.py`, `seo_audit.py`, `seo_optimizer.py` (Python 3 standard library only).
- `reports/`: baseline and implementation reports, latest audit.

## Before publishing a change

```
python3 scripts/sync_layout.py
python3 scripts/build_sitemap.py
python3 scripts/seo_audit.py --strict
```

The same checks run in GitHub Actions (`strativa-site-checks.yml`). To preview locally: `python3 -m http.server 8000`.
