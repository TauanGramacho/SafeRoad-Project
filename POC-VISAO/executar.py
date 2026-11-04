"""Prova de conceito: avaliação do YOLO11n em cenas de trânsito.

Percorre as quatro etapas da avaliação: carrega as anotações de referência,
carrega o modelo, executa a inferência sobre as mesmas imagens e compara as
predições com as referências, produzindo as métricas usuais de detecção.

Exemplos de uso:

    python executar.py --imagens dados/bdd100k/images/100k/val \\
                       --rotulos dados/bdd100k/labels/det_val.json \\
                       --limite 500

    python executar.py --imagens dados/meu_conjunto/valid/images \\
                       --classes dados/meu_conjunto/data.yaml
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Garante que os módulos do projeto sejam encontrados mesmo quando o programa é
# executado a partir de outro diretório.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
from avaliacao import (  # noqa: E402
    MetricasClasse,
    ResultadoImagem,
    avaliar,
    avaliar_por_porte,
    filtrar_por_lado_minimo,
    map_por_faixa_de_iou,
    media_das_precisoes,
)
from dataset import ErroDataset, carregar
from mapeamento import (
    CLASSES_DE_INTERESSE,
    EXCLUSOES_JUSTIFICADAS,
    rotulos_sem_equivalente,
)
from modelo import ErroModelo, carregar_modelo, inferir
from relatorio import (
    gravar_csv,
    gravar_json,
    montar_relatorio,
    tabela,
    tabela_por_atributo,
)


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Avalia o YOLO11n em um conjunto de imagens de trânsito.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--imagens", type=Path, required=True, help="Pasta com as imagens."
    )
    parser.add_argument(
        "--rotulos",
        type=Path,
        help="Arquivo JSON de rótulos do BDD100K.",
    )
    parser.add_argument(
        "--pasta-rotulos",
        type=Path,
        help="Pasta com os arquivos .txt no formato YOLO.",
    )
    parser.add_argument(
        "--classes",
        type=Path,
        help="data.yaml ou classes.txt com os nomes das classes do conjunto.",
    )
    parser.add_argument(
        "--modelo", default=config.MODELO_PADRAO, help="Pesos do YOLO."
    )
    parser.add_argument(
        "--limite",
        type=int,
        help="Número máximo de imagens avaliadas. Útil para ensaios rápidos.",
    )
    parser.add_argument(
        "--iou", type=float, default=config.IOU_PADRAO, help="Limiar de IoU."
    )
    parser.add_argument(
        "--confianca",
        type=float,
        default=config.CONFIANCA_OPERACIONAL,
        help="Limiar de confiança do ponto de operação.",
    )
    parser.add_argument(
        "--tamanho",
        type=int,
        default=config.TAMANHO_INFERENCIA,
        help="Resolução de inferência.",
    )
    parser.add_argument(
        "--lote", type=int, default=16, help="Imagens por lote de inferência."
    )
    parser.add_argument(
        "--lado-minimo",
        type=float,
        default=0.0,
        help=(
            "Descarta da avaliação os objetos cujo menor lado, em pixels, "
            "fique abaixo deste valor. Aplica-se igualmente a referências e "
            "predições. O padrão, zero, não descarta nada."
        ),
    )
    parser.add_argument(
        "--saida",
        type=Path,
        default=config.PASTA_RESULTADOS,
        help="Pasta onde os resultados são gravados.",
    )
    return parser


def agrupar_por_atributo(
    resultados: list[ResultadoImagem], atributo: str
) -> dict[str, list[ResultadoImagem]]:
    grupos: dict[str, list[ResultadoImagem]] = {}
    for resultado in resultados:
        valor = resultado.atributos.get(atributo)
        if not valor or valor in {"undefined", "NA"}:
            continue
        grupos.setdefault(f"{atributo}: {valor}", []).append(resultado)
    return grupos


def main(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)
    classes = sorted(CLASSES_DE_INTERESSE)

    try:
        # Etapa 1: anotações de referência.
        print("Carregando anotações de referência...")
        conjunto = carregar(
            pasta_imagens=args.imagens,
            arquivo_rotulos=args.rotulos,
            pasta_rotulos=args.pasta_rotulos,
            arquivo_classes=args.classes,
            limite=args.limite,
        )
        print(
            f"  formato: {conjunto.formato} | imagens: {len(conjunto.amostras)} "
            f"| anotações aproveitadas: {conjunto.anotacoes_aproveitadas}"
        )
        if conjunto.imagens_ausentes:
            print(
                f"  atenção: {conjunto.imagens_ausentes} imagens citadas nos "
                "rótulos não foram encontradas na pasta informada."
            )
        if conjunto.anotacoes_excluidas:
            print("  anotações excluídas por ausência de equivalente no COCO:")
            for rotulo, quantidade in sorted(
                conjunto.anotacoes_excluidas.items(),
                key=lambda item: -item[1],
            ):
                justificativa = EXCLUSOES_JUSTIFICADAS.get(rotulo, "")
                sufixo = f" ({justificativa})" if justificativa else ""
                print(f"    {rotulo}: {quantidade}{sufixo}")

        # Etapa 2: modelo, já restrito às classes de interesse.
        print(f"\nCarregando o modelo {args.modelo}...")
        modelo = carregar_modelo(args.modelo)
        print(
            "  classes consideradas: "
            + ", ".join(CLASSES_DE_INTERESSE[c] for c in classes)
        )

        # Etapa 3: inferência.
        print(f"\nExecutando a inferência em {len(conjunto.amostras)} imagens...")
        caminhos = [amostra.caminho for amostra in conjunto.amostras]
        predicoes, custo = inferir(
            modelo=modelo,
            caminhos=caminhos,
            classes_de_interesse=set(classes),
            confianca_minima=config.CONFIANCA_MINIMA,
            tamanho=args.tamanho,
            lote=args.lote,
        )
        print(
            f"  {custo.imagens} imagens em {custo.segundos:.1f} s "
            f"({custo.quadros_por_segundo:.1f} img/s, "
            f"{custo.milissegundos_por_imagem:.0f} ms por imagem)"
        )

        # Etapa 4: avaliação.
        print("\nComparando predições e referências...")
        resultados = [
            ResultadoImagem(
                indice=posicao,
                predicoes=predicoes[posicao],
                referencias=amostra.anotacoes,
                atributos=amostra.atributos,
            )
            for posicao, amostra in enumerate(conjunto.amostras)
        ]
        resultados, refs_fora, preds_fora = filtrar_por_lado_minimo(
            resultados, args.lado_minimo
        )
        if args.lado_minimo > 0:
            print(
                f"  objetos com lado inferior a {args.lado_minimo:.0f} px "
                f"descartados: {refs_fora} referências e {preds_fora} predições"
            )

        metricas = avaliar(resultados, classes, args.iou, args.confianca)
        map_por_iou = map_por_faixa_de_iou(
            resultados, classes, config.IOU_FAIXA, args.confianca
        )

        recortes: dict[str, dict[int, MetricasClasse]] = {}
        for atributo in ("timeofday", "weather", "scene"):
            for nome, grupo in agrupar_por_atributo(resultados, atributo).items():
                recortes[nome] = avaliar(grupo, classes, args.iou, args.confianca)

        # Apresentação.
        por_porte = avaliar_por_porte(
            resultados, classes, args.iou, args.confianca
        )

        print()
        print(tabela(metricas))
        media_faixa = sum(map_por_iou.values()) / len(map_por_iou)
        print(f"\nmAP@0,5:0,95: {media_faixa:.3f}")

        print("\nDesempenho por porte do objeto (faixas do COCO):")
        cabecalho = (
            f"{'porte':<12}{'refs':>8}{'VP':>7}{'FN':>7}"
            f"{'precisão':>11}{'revocação':>11}{'mAP@0,5':>10}"
        )
        print(cabecalho)
        print("-" * len(cabecalho))
        for nome in ("pequeno", "medio", "grande"):
            item = por_porte[nome]
            refs = sum(m.referencias for m in item.values())
            vp = sum(m.verdadeiros_positivos for m in item.values())
            fn = sum(m.falsos_negativos for m in item.values())
            fp = sum(m.falsos_positivos for m in item.values())
            precisao = vp / (vp + fp) if (vp + fp) else 0.0
            revocacao = vp / refs if refs else 0.0
            print(
                f"{nome:<12}{refs:>8}{vp:>7}{fn:>7}"
                f"{precisao:>11.3f}{revocacao:>11.3f}"
                f"{media_das_precisoes(item):>10.3f}"
            )
        if recortes:
            print("\nDesempenho por condição de captura:")
            print(tabela_por_atributo(recortes))

        parametros = {
            "modelo": args.modelo,
            "imagens_avaliadas": len(conjunto.amostras),
            "formato_do_conjunto": conjunto.formato,
            "limiar_iou": args.iou,
            "confianca_operacional": args.confianca,
            "confianca_minima_inferencia": config.CONFIANCA_MINIMA,
            "resolucao_inferencia": args.tamanho,
            "classes_avaliadas": [CLASSES_DE_INTERESSE[c] for c in classes],
            "lado_minimo_px": args.lado_minimo,
            "referencias_descartadas_por_tamanho": refs_fora,
            "predicoes_descartadas_por_tamanho": preds_fora,
            "rotulos_sem_equivalente": rotulos_sem_equivalente(),
        }
        relatorio = montar_relatorio(
            parametros=parametros,
            metricas=metricas,
            map_por_iou=map_por_iou,
            recortes={**recortes, **{f"porte: {k}": v for k, v in por_porte.items()}},
            exclusoes=conjunto.anotacoes_excluidas,
            custo={
                "imagens": custo.imagens,
                "segundos": round(custo.segundos, 2),
                "imagens_por_segundo": round(custo.quadros_por_segundo, 2),
                "milissegundos_por_imagem": round(
                    custo.milissegundos_por_imagem, 1
                ),
            },
        )
        gravar_json(args.saida / "relatorio.json", relatorio)
        gravar_csv(args.saida / "metricas-por-classe.csv", metricas)
        print(f"\nRelatório: {args.saida / 'relatorio.json'}")
        print(f"Planilha:  {args.saida / 'metricas-por-classe.csv'}")
        print(f"\nmAP@0,5 geral: {media_das_precisoes(metricas):.3f}")

    except (ErroDataset, ErroModelo) as erro:
        print(f"\nErro: {erro}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nExecução interrompida.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
