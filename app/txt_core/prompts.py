"""AI action prompts, ported byte-faithful from txt.ps1.

Each builder mirrors the legacy here-string prompt exactly, including the
trailing newline of the PS here-string syntax.
"""
from __future__ import annotations

import re


def consult_prompt(text: str) -> str:
    """Prompt for the Consultar action (txt.ps1 ~6521).

    S11: keeps the legacy base but forbids echoing the question (the reported
    "Consulta AI repite la pregunta") and directs web-enabled models to
    actually research and synthesize instead of restating the input.
    """
    return (
        "Respondé de manera clara, precisa y útil la siguiente consulta.\n"
        "Devolvé solamente la respuesta, sin introducciones innecesarias.\n"
        "No repitas, parafrasees, cites ni reformules la consulta: arrancá directo con la respuesta.\n"
        "Si tenés búsqueda web disponible, investigá el tema, contrastá fuentes y sintetizá lo encontrado en la respuesta.\n"
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
        "Si el texto ya está correcto, devuélvelo exactamente igual, sin avisar que no hacía falta corregirlo.\n"
        "Tu respuesta debe contener únicamente el texto, sin ninguna línea agregada antes ni después.\n"
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


FLOWCHART_PALETTE = (
    ("inicio", "#1E293B", "#0F172A"),
    ("decision", "#6366F1", "#4338CA"),
    ("proceso", "#3B82F6", "#1D4ED8"),
    ("exito", "#10B981", "#047857"),
    ("alerta", "#F59E0B", "#B45309"),
    ("error", "#EF4444", "#B91C1C"),
    ("datos", "#8B5CF6", "#5B21B6"),
)


def flowchart_prompt(text: str) -> str:
    """Prompt for the «Diagrama de flujo» action: a professional, colored
    Mermaid flowchart of the requested topic, and nothing else."""
    styles = "\n".join(
        f"    classDef {name} fill:{fill},stroke:{stroke},stroke-width:2px,color:#FFFFFF;"
        for name, fill, stroke in FLOWCHART_PALETTE)
    return (
        "Actuá como diseñador profesional de diagramas de flujo.\n"
        "Creá un diagrama de flujo profesional y a color sobre el tema indicado.\n"
        "\n"
        "Requisitos:\n"
        "- Devolvé un bloque de código Mermaid (```mermaid ... ```) y, debajo, una leyenda breve "
        "en lista que explique qué significa cada color. Nada más.\n"
        "- Empezá con `flowchart TD`.\n"
        "- Si el tema tiene partes claras (por ejemplo cliente, servidor y datos), agrupá los nodos en "
        "pocas áreas con `subgraph Id [\"Título\"] ... end`; ordená el flujo de arriba hacia abajo y "
        "evitá las flechas que vuelvan hacia arriba o crucen todo el diagrama.\n"
        "- Empezá el texto de cada nodo con un emoji que represente su función.\n"
        "- Copiá estas definiciones de estilo al comienzo del diagrama, sin cambiarlas:\n"
        f"{styles}\n"
        "- Aplicá un estilo a cada nodo con `:::` según su rol: inicio (inicio y fin), decision (preguntas), "
        "proceso (pasos), exito (resultados correctos), alerta (advertencias), error (fallos) y datos "
        "(bases de datos o archivos).\n"
        "- Usá formas según el rol: `([texto])` para inicio y fin, `{texto}` para decisiones, "
        "`[texto]` para pasos y `[(texto)]` para datos.\n"
        "- Escribí el texto de cada nodo entre comillas dobles, breve y en español, con las comillas "
        "pegadas al corchete: `A1([\"Inicio\"])`, nunca `A1([ \"Inicio\" ])`.\n"
        "- Rotulá las flechas que salen de una decisión (por ejemplo `-- \"Sí\" -->` y `-- \"No\" -->`).\n"
        "- Usá identificadores simples sin espacios ni acentos (A1, Validar, Guardar).\n"
        "- Cubrí el flujo completo, incluidos los caminos de error, con entre 8 y 24 nodos.\n"
        "\n"
        "Tema:\n"
        f"{text}\n"
    )


_SPACE_AFTER_OPEN = re.compile(r'([\[({])[ \t]+"')
_SPACE_BEFORE_CLOSE = re.compile(r'"[ \t]+([\])}])')
_DIAGRAM_START = re.compile(r"^(flowchart|graph)\s", re.MULTILINE)
# A line of prose after the diagram: a bullet, a heading or a "Leyenda:" title.
_PROSE_LINE = re.compile(r"^\s*([*#]|-\s|\d+\.\s|[^\[\](){}<>|=;]+:\s*$)")


def repair_mermaid(code: str) -> str:
    """Models often pad node labels (`[ "Inicio" ]`); Mermaid only accepts
    the quote right next to the bracket (`["Inicio"]`)."""
    return _SPACE_BEFORE_CLOSE.sub(r'"\1', _SPACE_AFTER_OPEN.sub(r'\1"', code))


def ensure_mermaid_block(answer: str) -> str:
    """The preview draws ```mermaid blocks: a model that answers with bare
    Mermaid code gets the fence added (any legend after it stays as text),
    and padded labels are repaired."""
    stripped = repair_mermaid((answer or "").strip())
    if "```mermaid" in stripped:
        return stripped
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        body = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        stripped = body.strip()
    start = _DIAGRAM_START.search(stripped)
    if not start:
        return stripped
    lines = stripped[start.start():].splitlines()
    end = len(lines)
    for index in range(1, len(lines)):
        if not lines[index - 1].strip() and _PROSE_LINE.match(lines[index]):
            end = index
            break
    code = "\n".join(lines[:end]).strip()
    legend = "\n".join(lines[end:]).strip()
    block = f"```mermaid\n{code}\n```"
    return f"{block}\n\n{legend}" if legend else block
