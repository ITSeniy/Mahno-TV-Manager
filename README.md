# mahno-tv-manager

> Portfolio project by Arseniy Makhonin.

An autonomous virtual TV channel director that schedules media, controls OBS, renders overlays, and maintains playout history.

## Highlights

- Maintained as a reproducible, source-first portfolio project.
- Build outputs, local secrets, proprietary dumps, and generated runtime data are excluded from version control.
- The repository keeps project documentation close to the implementation.

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

Репозиторий оформлен как портфолио: локальные секреты, результаты сборки и сторонние игровые/медиафайлы не должны попадать в Git.
