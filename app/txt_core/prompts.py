"""AI action prompts, ported byte-faithful from txt.ps1.

Each builder mirrors the legacy here-string prompt exactly, including the
trailing newline of the PS here-string syntax.
"""
from __future__ import annotations


def consult_prompt(text: str) -> str:
    """Prompt for the Consultar action (txt.ps1 ~6521)."""
    return (
        "Respondé de manera clara, precisa y útil la siguiente consulta.\n"
        "Devolvé solamente la respuesta, sin introducciones innecesarias.\n"
        "\n"
        "Consulta:\n"
        f"{text}\n"
    )


def summarize_prompt(text: str) -> str:
    """Prompt for the Resumir action (txt.ps1 ~6554)."""
    return (
        "Actuá como analista profesional, clasificador y ejemplificador experto.\n"
        "Creá un resumen de nivel profesional del contenido proporcionado.\n"
        "\n"
        "Requisitos:\n"
        "- Identificá el tema, el tipo de información y su objetivo principal.\n"
        "- Organizá las ideas en categorías claras y jerárquicas.\n"
        "- Destacá conceptos, datos y conclusiones esenciales.\n"
        "- Agregá ejemplos concretos cuando ayuden a comprender el contenido.\n"
        "- Conservá los detalles técnicos importantes y no inventes información.\n"
        "- Adaptá la extensión del resumen a la complejidad del material.\n"
        "- Entregá el resultado en Markdown claro y bien estructurado.\n"
        "\n"
        "Contenido:\n"
        f"{text}\n"
    )


def correct_prompt(text: str) -> str:
    """Prompt for the Corregir action (txt.ps1 ~6355)."""
    return (
        "Actúa como un corrector experto en redacción en español.\n"
        "Tu tarea es revisar y mejorar el texto que te voy a dar,\n"
        "asegurándote de que la gramática, la ortografía y la sintaxis sean impecables.\n"
        "\n"
        "Corrige únicamente la ortografía, la gramática y la puntuación del siguiente texto en español.\n"
        "No agregues contenido, no inventes contexto, no cambies el significado ni el tono.\n"
        "Mantén la estructura original tanto como sea posible.\n"
        "No reescribas con estilo narrativo, emocional ni conversacional.\n"
        "No añadas frases nuevas, ni introducciones, ni cierres.\n"
        "Dame solo el texto corregido, sin explicaciones ni comentarios.\n"
        "\n"
        "Texto original:\n"
        f"{text}\n"
    )


def translate_prompt(text: str, source_language: str, target_language: str) -> str:
    """Prompt for the Traducir action (txt.ps1 ~5977)."""
    return (
        f"Traducí el siguiente texto del {source_language} al {target_language}.\n"
        "Conservá el significado, el tono, el formato y los saltos de línea.\n"
        "Devolvé solamente la traducción, sin explicaciones, etiquetas ni comentarios.\n"
        "\n"
        "Texto original:\n"
        f"{text}\n"
    )
