# Ontwikkelen

## Tests draaien

```bash
uv venv --python 3.13
uv pip install pytest-homeassistant-custom-component home-assistant-frontend openpyxl ruff
.venv/bin/ruff check .
.venv/bin/python -m pytest
```

Dezelfde controles draaien op GitHub bij elke push, samen met hassfest en de HACS-validatie.

## Icoon aanpassen

Het icoon wordt getekend door `tools/make_icon.py` (Pillow). Pas de kleuren of maten daar aan en
draai het script; het schrijft `icon.png`, `icon@2x.png` en de `dark_` varianten naar
`custom_components/ere_report/brand/`.

## Nieuwe versie uitbrengen

1. Verhoog `version` in `custom_components/ere_report/manifest.json`.
2. Commit en push naar `main`, en wacht tot de controles groen zijn.
3. Maak een release met dezelfde versie als tag, bijvoorbeeld `v0.2.6`. HACS biedt de update
   daarna aan.
