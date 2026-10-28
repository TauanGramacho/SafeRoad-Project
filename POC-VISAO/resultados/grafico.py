"""Gráficos comparativos das execuções da prova de conceito.

Produz dois gráficos de barras com eixo horizontal de dois níveis, classe e
execução: o primeiro com as contagens absolutas, o segundo com as taxas.

Uso:
    python grafico.py resultados/completo/relatorio.json \\
                      resultados/lado20/relatorio.json \\
                      --nomes "Sem recorte" "Lado mínimo 20 px"
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import plotly.graph_objects as go

# Paleta categórica validada para daltonismo, modo claro. A ordem é o mecanismo
# de segurança e não deve ser rearranjada.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
SURFACE = "#fcfcfb"
TEXTO = "#0b0b0b"
TEXTO2 = "#52514e"
GRADE = "#e7e6e1"

CONTAGENS = [
    ("referencias", "Referências"),
    ("verdadeiros_positivos", "Verdadeiros positivos"),
    ("falsos_positivos", "Falsos positivos"),
    ("falsos_negativos", "Falsos negativos"),
]
TAXAS = [
    ("precisao", "Precisão"),
    ("revocacao", "Revocação"),
    ("f1", "F1"),
]

# Formato dos rótulos sobre as barras, na notação do Plotly. O separador de
# milhar e o decimal são definidos no layout, em padrão brasileiro.
FORMATO_CONTAGEM = "%{y:,.0f}"
FORMATO_TAXA = "%{y:.3f}"


def ler(caminho: Path) -> dict[str, dict[str, float]]:
    """Lê um relatório em JSON ou CSV e devolve as métricas por classe."""
    if caminho.suffix.lower() == ".csv":
        linhas = csv.DictReader(caminho.read_text(encoding="utf-8").splitlines())
        return {
            linha["classe"]: {
                chave: float(valor)
                for chave, valor in linha.items()
                if chave != "classe" and valor
            }
            for linha in linhas
        }
    conteudo = json.loads(caminho.read_text(encoding="utf-8"))
    return {
        classe: {
            chave: float(valor)
            for chave, valor in valores.items()
            if isinstance(valor, (int, float))
        }
        for classe, valores in conteudo["metricas_por_classe"].items()
    }


def eixo_duplo(
    classes: list[str], nomes: list[str]
) -> tuple[list[str], list[str]]:
    """Monta os dois níveis do eixo horizontal, classe e execução."""
    nivel_classe = [classe for classe in classes for _ in nomes]
    nivel_execucao = [nome for _ in classes for nome in nomes]
    return nivel_classe, nivel_execucao


def valores_do_campo(
    relatorios: list[dict[str, dict[str, float]]],
    classes: list[str],
    campo: str,
) -> list[float | None]:
    """Extrai os valores de um campo, na ordem do eixo duplo."""
    return [
        relatorio.get(classe, {}).get(campo)
        for classe in classes
        for relatorio in relatorios
    ]


def montar_figura(
    relatorios: list[dict[str, dict[str, float]]],
    nomes: list[str],
    classes: list[str],
    campos: list[tuple[str, str]],
    titulo: str,
    titulo_y: str,
    log: bool,
    formato: str,
    rotulos: bool = True,
    tamanho_rotulo: int = 9,
) -> go.Figure:
    """Monta um gráfico de barras agrupadas com eixo horizontal de dois níveis."""
    eixo = eixo_duplo(classes, nomes)
    figura = go.Figure()
    for posicao, (campo, rotulo) in enumerate(campos):
        figura.add_bar(
            name=rotulo,
            x=eixo,
            y=valores_do_campo(relatorios, classes, campo),
            marker_color=SERIES[posicao % len(SERIES)],
            marker_line_width=0,
            hovertemplate=f"<b>{rotulo}</b><br>%{{x}}<br>%{{y}}<extra></extra>",
            texttemplate=formato if rotulos else None,
            textposition="outside" if rotulos else "none",
            textangle=0,
            textfont=dict(size=tamanho_rotulo, color=TEXTO),
            # Impede que o rótulo da barra mais alta seja cortado pelo topo.
            cliponaxis=False,
        )

    figura.update_layout(
        title=dict(text=titulo, x=0, xanchor="left", font=dict(size=17)),
        barmode="group",
        bargap=0.28,
        bargroupgap=0.08,
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        font=dict(family="system-ui, Segoe UI, Roboto, sans-serif", color=TEXTO),
        margin=dict(l=70, r=24, t=70, b=90),
        legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0, xanchor="left"),
        height=600,
        # Separadores em padrão brasileiro: decimal com vírgula, milhar com ponto.
        separators=",.",
        uniformtext=dict(mode="show", minsize=10),
    )
    figura.update_xaxes(
        showgrid=False, linecolor=GRADE, tickfont=dict(size=11, color=TEXTO2)
    )
    figura.update_yaxes(
        title=dict(text=titulo_y, font=dict(size=13)),
        gridcolor=GRADE,
        zerolinecolor=GRADE,
        linecolor=GRADE,
        type="log" if log else "linear",
        rangemode="normal" if log else "tozero",
    )
    # Folga no topo para que os rótulos externos caibam dentro da área do gráfico.
    if rotulos and not log:
        maximo = max(
            (valor for traco in figura.data for valor in traco.y if valor is not None),
            default=1.0,
        )
        figura.update_yaxes(range=[0, maximo * 1.22])
    return figura


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("entradas", type=Path, nargs="+")
    parser.add_argument("--nomes", nargs="+")
    parser.add_argument("--ignorar", nargs="*", default=["placa_pare", "semaforo"])
    parser.add_argument(
        "--linear",
        action="store_true",
        help="Escala linear nas contagens, em vez de logarítmica.",
    )
    parser.add_argument(
        "--sem-rotulos",
        action="store_true",
        help="Omite os valores sobre as barras, deixando-os apenas no hover.",
    )
    parser.add_argument(
        "--tamanho-rotulo",
        type=int,
        default=12,
        help="Corpo da fonte dos valores sobre as barras.",
    )
    parser.add_argument("--saida", type=Path, default=Path("resultados"))
    args = parser.parse_args()

    relatorios = [ler(caminho) for caminho in args.entradas]
    nomes = args.nomes or [caminho.parent.name for caminho in args.entradas]
    ignorar = {item.lower() for item in (args.ignorar or [])}
    classes = sorted(
        {
            classe
            for relatorio in relatorios
            for classe in relatorio
            if classe.lower() not in ignorar
        }
    )

    log = not args.linear
    rotulos = not args.sem_rotulos
    figura_contagens = montar_figura(
        relatorios,
        nomes,
        classes,
        CONTAGENS,
        "Contagens por classe e execução",
        "Objetos (escala logarítmica)" if log else "Objetos",
        log,
        FORMATO_CONTAGEM,
        rotulos,
        args.tamanho_rotulo,
    )
    figura_taxas = montar_figura(
        relatorios,
        nomes,
        classes,
        TAXAS,
        "Precisão, revocação e F1 por classe e execução",
        "Valor (0 a 1)",
        False,
        FORMATO_TAXA,
        rotulos,
        args.tamanho_rotulo,
    )

    args.saida.mkdir(parents=True, exist_ok=True)
    for nome, figura in (
        ("contagens", figura_contagens),
        ("taxas", figura_taxas),
    ):
        destino = args.saida / f"{nome}.html"
        figura.write_html(destino, include_plotlyjs="cdn")
        print(f"{destino}")
        try:
            figura.write_image(args.saida / f"{nome}.png", scale=3)
            print(f"{args.saida / f'{nome}.png'}")
        except Exception:
            pass  # exportação em imagem exige o pacote kaleido

    print(f"\nClasses: {', '.join(classes)}")
    print(f"Execuções: {', '.join(nomes)}")


if __name__ == "__main__":
    main()
