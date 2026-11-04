"""Diagnóstico do conjunto de avaliação.

Descreve a distribuição de tamanho das anotações de referência, informação
necessária para interpretar a revocação: objetos muito pequenos podem estar
abaixo do limite de resolução do modelo e produzir falsos negativos que não
decorrem de falha do detector, mas da escala em que a inferência é executada.

Uso:
    python diagnostico.py --imagens data/train --limite 200
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dataset import ErroDataset, carregar  # noqa: E402
from mapeamento import nome_da_classe  # noqa: E402

# Faixas do COCO: pequeno abaixo de 32x32, médio até 96x96, grande acima.
LIMITE_PEQUENO = 32 * 32
LIMITE_MEDIO = 96 * 96


def faixa(area: float) -> str:
    if area < LIMITE_PEQUENO:
        return "pequeno"
    if area < LIMITE_MEDIO:
        return "medio"
    return "grande"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Descreve a distribuição de tamanho das anotações."
    )
    parser.add_argument("--imagens", type=Path, required=True)
    parser.add_argument("--rotulos", type=Path)
    parser.add_argument("--pasta-rotulos", type=Path)
    parser.add_argument("--classes", type=Path)
    parser.add_argument("--limite", type=int)
    args = parser.parse_args(argv)

    try:
        conjunto = carregar(
            pasta_imagens=args.imagens,
            arquivo_rotulos=args.rotulos,
            pasta_rotulos=args.pasta_rotulos,
            arquivo_classes=args.classes,
            limite=args.limite,
        )
    except ErroDataset as erro:
        print(f"Erro: {erro}", file=sys.stderr)
        return 1

    por_classe: dict[int, dict[str, int]] = {}
    larguras: list[float] = []
    alturas: list[float] = []
    total = 0
    for amostra in conjunto.amostras:
        for anotacao in amostra.anotacoes:
            caixa = anotacao.caixa
            contagem = por_classe.setdefault(
                anotacao.classe, {"pequeno": 0, "medio": 0, "grande": 0}
            )
            contagem[faixa(caixa.area)] += 1
            larguras.append(caixa.x2 - caixa.x1)
            alturas.append(caixa.y2 - caixa.y1)
            total += 1

    if total == 0:
        print("Nenhuma anotação aproveitada.")
        return 1

    print(f"Imagens: {len(conjunto.amostras)} | anotações: {total}")
    print(f"Anotações por imagem: {total / len(conjunto.amostras):.1f}\n")

    cabecalho = (
        f"{'classe':<12}{'total':>8}{'pequeno':>10}{'médio':>9}{'grande':>9}"
        f"{'% pequeno':>12}"
    )
    print(cabecalho)
    print("-" * len(cabecalho))
    for classe in sorted(por_classe, key=nome_da_classe):
        contagem = por_classe[classe]
        soma = sum(contagem.values())
        print(
            f"{nome_da_classe(classe):<12}{soma:>8}"
            f"{contagem['pequeno']:>10}{contagem['medio']:>9}"
            f"{contagem['grande']:>9}"
            f"{100 * contagem['pequeno'] / soma:>11.1f}%"
        )

    larguras.sort()
    alturas.sort()

    def percentil(valores: list[float], posicao: float) -> float:
        indice = min(int(posicao * len(valores)), len(valores) - 1)
        return valores[indice]

    print("\nDimensões das caixas de referência, em pixels:")
    for rotulo, posicao in (
        ("mínimo", 0.0),
        ("1º quartil", 0.25),
        ("mediana", 0.50),
        ("3º quartil", 0.75),
        ("máximo", 0.999),
    ):
        print(
            f"  {rotulo:<12} largura {percentil(larguras, posicao):>7.1f}"
            f"   altura {percentil(alturas, posicao):>7.1f}"
        )

    minusculas = sum(
        1
        for largura, altura in zip(larguras, alturas, strict=True)
        if largura < 16 or altura < 16
    )
    print(
        f"\nAnotações com algum lado abaixo de 16 pixels: {minusculas} "
        f"({100 * minusculas / total:.1f}%)"
    )
    print(
        "Na resolução padrão de inferência (640 sobre imagens de 1280), esses "
        "objetos ocupam menos de 8 pixels e estão próximos ao limite de\n"
        "detecção do modelo."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
