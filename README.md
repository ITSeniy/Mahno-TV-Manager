# mahno-tv-manager

An autonomous virtual TV channel director that schedules media, controls OBS, renders overlays, and maintains playout history.

## Technology

JavaScript / TypeScript, Python

## Repository layout

Primary areas: `data/`, `ntsc-rs-windows-openfx/`, `ntsc-rs-windows-standalone/`, `spikes/`, `src/`, `tests/`.

## Build and verification

```bash
python -m venv .venv
pip install -e .
python -m pytest
```

Exact requirements may vary by platform. Check project-specific documentation and configuration before building.

## Legal

Original source code is available under the MIT License. Third-party dependencies retain their respective licenses.

## Русский

Автономный диспетчер виртуального телеканала: планирует эфир, управляет OBS, создаёт оверлеи и ведёт историю вещания.

Создавался для ретро-канала в стиле REN-TV начала нулевых годов.
