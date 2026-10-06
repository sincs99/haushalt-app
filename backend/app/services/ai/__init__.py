"""KI-Assistent: Anbindung an die Claude API über das offizielle ``anthropic``-SDK.

Aufbau (Details in ``docs/ai-assistant.md``):

- ``client``   — Client-Factory und der eine gemeinsame, strukturierte API-Aufruf
- ``prompts``  — Systemprompts (DE/EN) und Aufbau der Nutzernachricht
- ``schemas``  — Eingabe- und Ausgabe-Schemas (Pydantic)
- ``usage``    — Tageslimit und Token-Zähler pro Haushalt
- ``recipe``, ``plant_care`` — je eine Funktion pro Feature
"""
