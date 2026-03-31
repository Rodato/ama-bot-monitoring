"""
agent_report.py
Orquestador del reporte semanal del bot AMA.
Genera el Excel y luego produce una narrativa via OpenRouter.

Uso:
    python3 src/agent_report.py --from 2026-03-02 --to 2026-03-09
    python3 src/agent_report.py --from 2026-03-02 --to 2026-03-09 --no-llm
    python3 src/agent_report.py --from 2026-03-02 --to 2026-03-09 --model anthropic/claude-sonnet-4-6
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import argparse
from dotenv import load_dotenv
from openai import OpenAI
import report_bot

load_dotenv()

DEFAULT_MODEL = "x-ai/grok-4"


# ── LLM ───────────────────────────────────────────────────────────────────────

def build_prompt(summary: str, fecha_inicio: str, fecha_fin: str) -> str:
    return f"""Eres un analista del programa educativo AMA. Tienes los datos de uso del bot WhatsApp para la semana del {fecha_inicio} al {fecha_fin}.

Los datos están organizados en tres dimensiones:
- Por Ciudad: usuarios activos por ciudad y género, por día
- Por Colegio: usuarios activos por institución y género, por día
- Por Salón: usuarios activos por salón/curso y género, por día

DATOS:
{summary}

Escribe un reporte narrativo en español, en prosa continua (sin títulos, sin secciones, sin bullets, sin markdown). Un solo bloque de texto de 4 a 6 párrafos cortos.

El reporte debe cubrir, en este orden:
1. Total de usuarios activos en la semana, distribución de género y días con mayor actividad.
2. Participación por ciudad: cuál lideró, porcentajes, diferencias relevantes.
3. Colegios con mayor y menor participación, con los números clave y patrones relevantes entre ciudades.
4. Si hay algo que llame la atención o requiera seguimiento (sin exagerar; omitir si no hay nada importante).

Reglas estrictas:
- Solo prosa. Ningún encabezado, bullet, numeración ni formato markdown.
- Usa los números reales de los datos. No inventes ni redondees innecesariamente.
- No menciones salones a menos que haya algo verdaderamente destacable.
- Tono profesional y directo. Sin frases de relleno ni conclusiones genéricas.
"""


def call_llm(prompt: str, model: str) -> str:
    client = OpenAI(
        api_key=os.getenv("OPENROUTER_API_KEY"),
        base_url="https://openrouter.ai/api/v1",
    )
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--from",    dest="fecha_inicio", required=True)
    parser.add_argument("--to",      dest="fecha_fin",    required=True)
    parser.add_argument("--out",     dest="out_dir", default="data/reports")
    parser.add_argument("--model",   dest="model",   default=DEFAULT_MODEL)
    parser.add_argument("--no-llm",  dest="no_llm",  action="store_true",
                        help="Generar solo el Excel, sin narrativa LLM")
    args = parser.parse_args()

    # 1. Generar Excel
    print(f"\n[agent_report] Generando reporte {args.fecha_inicio} → {args.fecha_fin}...")
    excel_path, summary = report_bot.generate_report(
        args.fecha_inicio, args.fecha_fin, args.out_dir
    )

    if args.no_llm:
        print("[agent_report] --no-llm activo. Listo.")
        return

    # 2. Llamar al LLM
    print(f"[agent_report] Generando narrativa con {args.model}...")
    prompt   = build_prompt(summary, args.fecha_inicio, args.fecha_fin)
    narrativa = call_llm(prompt, args.model)

    # 3. Guardar markdown
    import os
    md_path = os.path.join(
        args.out_dir, f"reporte_bot_{args.fecha_inicio}_{args.fecha_fin}.md"
    )
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# Reporte Bot AMA — {args.fecha_inicio} al {args.fecha_fin}\n\n")
        f.write(narrativa)

    print(f"[agent_report] Narrativa guardada en: {md_path}")
    print("\n" + "="*60)
    print(narrativa)
    print("="*60)


if __name__ == "__main__":
    main()
