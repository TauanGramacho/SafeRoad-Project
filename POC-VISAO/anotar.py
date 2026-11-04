"""Desenha as detecções do modelo sobre uma imagem.

Recebe o caminho de uma ou mais imagens, executa a inferência com os mesmos
parâmetros e o mesmo filtro de classes usados na avaliação, e grava uma cópia
anotada com as caixas delimitadoras, a classe e a confiança de cada detecção.

Destina-se à inspeção visual e à produção de figuras ilustrativas, e não à
avaliação quantitativa, que é objeto de executar.py.

Uso:
    python anotar.py caminho/para/imagem.jpg
    python anotar.py data/train/img/*.jpg --confianca 0.4 --saida result
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

import config  # noqa: E402
from avaliacao import Predicao  # noqa: E402
from mapeamento import CLASSES_DE_INTERESSE, nome_da_classe  # noqa: E402
from modelo import ErroModelo, carregar_modelo, inferir  # noqa: E402

# Paleta categórica validada para daltonismo. A cor acompanha a classe, e não a
# ordem em que as detecções aparecem, de modo que a mesma classe recebe sempre a
# mesma cor em todas as imagens.
CORES = {
    0: "#2a78d6",   # pessoa
    1: "#eb6834",   # bicicleta
    2: "#1baf7a",   # carro
    3: "#eda100",   # motocicleta
    5: "#e87ba4",   # onibus
    7: "#008300",   # caminhao
    9: "#6250d6",   # semaforo
    11: "#e34948",  # placa de pare
}
COR_PADRAO = "#52514e"
TINTA_ROTULO = "#ffffff"

# Fontes tentadas em ordem, cobrindo Linux, Windows e macOS.
FONTES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]


def carregar_fonte(altura: int) -> ImageFont.ImageFont:
    """Escolhe um corpo de fonte proporcional à altura da imagem."""
    corpo = max(13, round(altura * 0.022))
    for caminho in FONTES:
        if Path(caminho).is_file():
            try:
                return ImageFont.truetype(caminho, corpo)
            except OSError:
                continue
    return ImageFont.load_default()


def medir(desenho: ImageDraw.ImageDraw, texto: str, fonte) -> tuple[int, int]:
    """Largura e altura de um texto, com o recuo do glifo já descontado."""
    esquerda, topo, direita, base = desenho.textbbox((0, 0), texto, font=fonte)
    return direita - esquerda, base - topo


def desenhar(
    imagem: Image.Image, predicoes: list[Predicao], espessura: int | None = None
) -> Image.Image:
    """Devolve uma cópia da imagem com as detecções desenhadas."""
    anotada = imagem.convert("RGB")
    desenho = ImageDraw.Draw(anotada)
    largura, altura = anotada.size
    fonte = carregar_fonte(altura)
    traco = espessura or max(2, round(altura * 0.004))

    # As detecções menores são desenhadas por último, de modo que seus rótulos
    # não fiquem encobertos pelos das detecções maiores.
    ordenadas = sorted(predicoes, key=lambda p: p.caixa.area, reverse=True)

    for predicao in ordenadas:
        caixa = predicao.caixa
        cor = CORES.get(predicao.classe, COR_PADRAO)
        desenho.rectangle(
            [caixa.x1, caixa.y1, caixa.x2, caixa.y2], outline=cor, width=traco
        )

        rotulo = f"{nome_da_classe(predicao.classe)} {predicao.confianca:.0%}"
        largura_texto, altura_texto = medir(desenho, rotulo, fonte)
        recuo = max(3, traco)
        largura_caixa = largura_texto + 2 * recuo
        altura_caixa = altura_texto + 2 * recuo

        # Acima da caixa quando houver espaço; dentro dela em caso contrário.
        topo = caixa.y1 - altura_caixa
        if topo < 0:
            topo = min(caixa.y1, altura - altura_caixa)
        esquerda = min(caixa.x1, largura - largura_caixa)
        esquerda = max(0.0, esquerda)

        desenho.rectangle(
            [esquerda, topo, esquerda + largura_caixa, topo + altura_caixa],
            fill=cor,
        )
        desenho.text(
            (esquerda + recuo, topo + recuo),
            rotulo,
            fill=TINTA_ROTULO,
            font=fonte,
        )
    return anotada


def destino(origem: Path, pasta: Path) -> Path:
    """Caminho de saída: mesmo nome, com o sufixo _plotted."""
    return pasta / f"{origem.stem}_plotted{origem.suffix or '.jpg'}"


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Desenha as detecções do modelo sobre uma imagem.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "imagens", type=Path, nargs="+", help="Imagens a anotar."
    )
    parser.add_argument("--modelo", default=config.MODELO_PADRAO)
    parser.add_argument(
        "--confianca",
        type=float,
        default=config.CONFIANCA_OPERACIONAL,
        help="Confiança mínima para que a detecção seja desenhada.",
    )
    parser.add_argument("--tamanho", type=int, default=config.TAMANHO_INFERENCIA)
    parser.add_argument(
        "--espessura",
        type=int,
        help="Espessura do traço, em pixels. O padrão acompanha a imagem.",
    )
    parser.add_argument(
        "--saida",
        type=Path,
        default=Path("result"),
        help="Pasta onde as imagens anotadas são gravadas.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)

    caminhos = [caminho for caminho in args.imagens if caminho.is_file()]
    ausentes = [caminho for caminho in args.imagens if not caminho.is_file()]
    for caminho in ausentes:
        print(f"Aviso: arquivo não encontrado, ignorado: {caminho}", file=sys.stderr)
    if not caminhos:
        print("Erro: nenhuma imagem válida informada.", file=sys.stderr)
        return 1

    try:
        modelo = carregar_modelo(args.modelo)
        predicoes, custo = inferir(
            modelo=modelo,
            caminhos=caminhos,
            classes_de_interesse=set(CLASSES_DE_INTERESSE),
            confianca_minima=args.confianca,
            tamanho=args.tamanho,
            progresso=len(caminhos) > 1,
        )
    except ErroModelo as erro:
        print(f"Erro: {erro}", file=sys.stderr)
        return 1

    args.saida.mkdir(parents=True, exist_ok=True)
    for caminho, deteccoes in zip(caminhos, predicoes, strict=True):
        try:
            with Image.open(caminho) as imagem:
                anotada = desenhar(imagem, deteccoes, args.espessura)
        except OSError as erro:
            print(f"Erro ao abrir {caminho}: {erro}", file=sys.stderr)
            continue

        arquivo = destino(caminho, args.saida)
        anotada.save(arquivo, quality=95)

        print(f"\n{caminho.name}: {len(deteccoes)} detecção(ões)")
        for predicao in sorted(
            deteccoes, key=lambda p: p.confianca, reverse=True
        ):
            print(
                f"  {nome_da_classe(predicao.classe):<12} "
                f"{predicao.confianca:>6.1%}"
            )
        print(f"  -> {arquivo}")

    print(
        f"\n{custo.imagens} imagem(ns) processada(s) em {custo.segundos:.2f} s "
        f"({custo.milissegundos_por_imagem:.0f} ms por imagem)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
