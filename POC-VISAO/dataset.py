"""Carregamento das anotações de referência.

Suporta três formatos: o do BDD100K oficial, distribuído como arquivo JSON
único; o formato Supervisely, com um JSON por imagem, usado pelas redistribuições
do conjunto; e o formato YOLO, com um arquivo de texto por imagem. O formato é
detectado automaticamente a partir dos caminhos informados.
"""

from __future__ import annotations

import base64
import json
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from mapeamento import converter_rotulo

EXTENSOES_IMAGEM = (".jpg", ".jpeg", ".png", ".bmp", ".webp")


@dataclass(frozen=True)
class Caixa:
    """Caixa delimitadora em coordenadas absolutas de pixel."""

    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def area(self) -> float:
        return max(0.0, self.x2 - self.x1) * max(0.0, self.y2 - self.y1)


@dataclass(frozen=True)
class Anotacao:
    """Objeto anotado em uma imagem de referência."""

    classe: int
    caixa: Caixa


@dataclass
class Amostra:
    """Imagem acompanhada de suas anotações e de seus atributos de cena."""

    caminho: Path
    anotacoes: list[Anotacao] = field(default_factory=list)
    atributos: dict[str, str] = field(default_factory=dict)


@dataclass
class ResumoCarregamento:
    """Registro do que foi carregado e do que foi descartado."""

    amostras: list[Amostra]
    formato: str
    anotacoes_aproveitadas: int = 0
    anotacoes_excluidas: dict[str, int] = field(default_factory=dict)
    imagens_ausentes: int = 0


class ErroDataset(Exception):
    pass


# ------------------------------------------------------------- BDD100K
def carregar_bdd100k(
    arquivo_rotulos: Path, pasta_imagens: Path, limite: int | None = None
) -> ResumoCarregamento:
    """Carrega anotações no formato JSON do BDD100K."""
    try:
        conteudo = json.loads(arquivo_rotulos.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as erro:
        raise ErroDataset(f"Não foi possível ler {arquivo_rotulos}: {erro}") from erro

    if not isinstance(conteudo, list):
        raise ErroDataset(
            "O arquivo de rótulos do BDD100K deve conter uma lista de imagens."
        )

    resumo = ResumoCarregamento(amostras=[], formato="bdd100k")
    for registro in conteudo:
        if limite is not None and len(resumo.amostras) >= limite:
            break
        nome = registro.get("name")
        if not nome:
            continue
        caminho = pasta_imagens / nome
        if not caminho.is_file():
            resumo.imagens_ausentes += 1
            continue

        anotacoes: list[Anotacao] = []
        for rotulo in registro.get("labels") or []:
            caixa_bruta = rotulo.get("box2d")
            if not caixa_bruta:
                continue  # polígonos de segmentação são ignorados
            categoria = str(rotulo.get("category", ""))
            classe = converter_rotulo(categoria)
            if classe is None:
                chave = categoria.strip().lower()
                resumo.anotacoes_excluidas[chave] = (
                    resumo.anotacoes_excluidas.get(chave, 0) + 1
                )
                continue
            anotacoes.append(
                Anotacao(
                    classe=classe,
                    caixa=Caixa(
                        float(caixa_bruta["x1"]),
                        float(caixa_bruta["y1"]),
                        float(caixa_bruta["x2"]),
                        float(caixa_bruta["y2"]),
                    ),
                )
            )
            resumo.anotacoes_aproveitadas += 1

        atributos = {
            chave: str(valor)
            for chave, valor in (registro.get("attributes") or {}).items()
        }
        resumo.amostras.append(
            Amostra(caminho=caminho, anotacoes=anotacoes, atributos=atributos)
        )

    if not resumo.amostras:
        raise ErroDataset(
            "Nenhuma imagem do arquivo de rótulos foi encontrada em "
            f"{pasta_imagens}. Verifique se a pasta corresponde à divisão "
            "(train, val) do arquivo informado."
        )
    return resumo


# -------------------------------------------------- formato Supervisely
def _caixa_de_vertices(vertices: list[list[float]]) -> Caixa | None:
    """Caixa envolvente de uma lista de vértices.

    Atende tanto ao polígono, cujos vértices descrevem o contorno do objeto,
    quanto ao retângulo, representado por dois vértices opostos.
    """
    if not vertices:
        return None
    xs = [float(ponto[0]) for ponto in vertices]
    ys = [float(ponto[1]) for ponto in vertices]
    return Caixa(min(xs), min(ys), max(xs), max(ys))


def _dimensoes_png(dados: bytes) -> tuple[int, int] | None:
    """Lê largura e altura do cabeçalho IHDR de um PNG, sem decodificá-lo."""
    if len(dados) < 24 or dados[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    largura, altura = struct.unpack(">II", dados[16:24])
    return int(largura), int(altura)


def _caixa_de_bitmap(bitmap: dict) -> Caixa | None:
    """Caixa envolvente de uma máscara.

    No formato Supervisely a máscara é recortada à própria caixa envolvente do
    objeto, de modo que a origem informada e as dimensões da imagem codificada
    bastam para reconstruí-la.
    """
    origem = bitmap.get("origin")
    dados = bitmap.get("data")
    if not origem or not dados:
        return None
    try:
        bruto = base64.b64decode(dados)
    except (ValueError, TypeError):
        return None
    dimensoes = _dimensoes_png(bruto)
    if dimensoes is None:
        # Algumas versões comprimem o PNG com zlib antes de codificar em base64.
        try:
            bruto = zlib.decompress(bruto)
        except zlib.error:
            return None
        dimensoes = _dimensoes_png(bruto)
    if dimensoes is None:
        return None
    largura, altura = dimensoes
    x1, y1 = float(origem[0]), float(origem[1])
    return Caixa(x1, y1, x1 + largura, y1 + altura)


def _caixa_do_objeto(objeto: dict) -> Caixa | None:
    """Extrai a caixa envolvente de um objeto, qualquer que seja sua geometria."""
    geometria = str(objeto.get("geometryType", "")).lower()
    if geometria == "bitmap":
        return _caixa_de_bitmap(objeto.get("bitmap") or {})
    pontos = objeto.get("points") or {}
    return _caixa_de_vertices(pontos.get("exterior") or [])


def _pasta_de_imagens(base: Path) -> Path | None:
    for nome in ("img", "images", "image"):
        candidata = base / nome
        if candidata.is_dir():
            return candidata
    return None


def carregar_supervisely(
    pasta_divisao: Path, limite: int | None = None
) -> ResumoCarregamento:
    """Carrega anotações no formato Supervisely, com um JSON por imagem.

    Espera uma pasta de divisão contendo as subpastas ``ann`` e ``img``, esta
    última eventualmente nomeada ``images``.
    """
    pasta_ann = pasta_divisao / "ann"
    if not pasta_ann.is_dir():
        raise ErroDataset(f"Subpasta de anotações não encontrada: {pasta_ann}")
    pasta_img = _pasta_de_imagens(pasta_divisao)
    if pasta_img is None:
        raise ErroDataset(
            f"Subpasta de imagens não encontrada em {pasta_divisao} "
            "(esperado 'img' ou 'images')."
        )

    arquivos = sorted(pasta_ann.glob("*.json"))
    if not arquivos:
        raise ErroDataset(f"Nenhuma anotação encontrada em {pasta_ann}.")

    resumo = ResumoCarregamento(amostras=[], formato="supervisely")
    for arquivo in arquivos:
        if limite is not None and len(resumo.amostras) >= limite:
            break
        # O nome do arquivo de anotação é o da imagem acrescido de '.json'.
        nome_imagem = arquivo.name[: -len(".json")]
        caminho = pasta_img / nome_imagem
        if not caminho.is_file():
            resumo.imagens_ausentes += 1
            continue
        try:
            conteudo = json.loads(arquivo.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            resumo.imagens_ausentes += 1
            continue

        anotacoes: list[Anotacao] = []
        for objeto in conteudo.get("objects") or []:
            titulo = str(objeto.get("classTitle", ""))
            classe = converter_rotulo(titulo)
            if classe is None:
                chave = titulo.strip().lower()
                resumo.anotacoes_excluidas[chave] = (
                    resumo.anotacoes_excluidas.get(chave, 0) + 1
                )
                continue
            caixa = _caixa_do_objeto(objeto)
            if caixa is None or caixa.area <= 0:
                continue
            anotacoes.append(Anotacao(classe=classe, caixa=caixa))
            resumo.anotacoes_aproveitadas += 1

        # As marcações de cena, quando presentes, viram atributos da amostra.
        atributos: dict[str, str] = {}
        for marcacao in conteudo.get("tags") or []:
            nome = marcacao.get("name")
            if nome:
                atributos[str(nome)] = str(marcacao.get("value") or "sim")

        resumo.amostras.append(
            Amostra(caminho=caminho, anotacoes=anotacoes, atributos=atributos)
        )

    if not resumo.amostras:
        raise ErroDataset(
            f"Nenhuma imagem de {pasta_img} corresponde às anotações de "
            f"{pasta_ann}."
        )
    return resumo


# ---------------------------------------------------------- formato YOLO
def _nomes_do_data_yaml(arquivo: Path) -> list[str]:
    """Extrai a lista de nomes de classe de um data.yaml sem exigir PyYAML."""
    texto = arquivo.read_text(encoding="utf-8")
    nomes: list[str] = []
    dentro = False
    for linha in texto.splitlines():
        despida = linha.strip()
        if despida.startswith("names:"):
            resto = despida[len("names:") :].strip()
            if resto.startswith("[") and resto.endswith("]"):
                return [
                    item.strip().strip("'\"")
                    for item in resto[1:-1].split(",")
                    if item.strip()
                ]
            dentro = True
            continue
        if dentro:
            if despida.startswith("-"):
                nomes.append(despida[1:].strip().strip("'\""))
            elif despida and not linha.startswith((" ", "\t")):
                break
    return nomes


def _dimensoes(caminho: Path) -> tuple[int, int]:
    try:
        from PIL import Image
    except ImportError as erro:  # pragma: no cover
        raise ErroDataset(
            "O formato YOLO exige a leitura das dimensões da imagem. "
            "Instale as dependências com 'pip install -r requirements.txt'."
        ) from erro
    with Image.open(caminho) as imagem:
        return imagem.width, imagem.height


def carregar_yolo(
    pasta_imagens: Path,
    pasta_rotulos: Path,
    nomes_classes: list[str],
    limite: int | None = None,
) -> ResumoCarregamento:
    """Carrega anotações no formato YOLO, com um arquivo de texto por imagem."""
    arquivos = sorted(
        caminho
        for caminho in pasta_imagens.iterdir()
        if caminho.suffix.lower() in EXTENSOES_IMAGEM
    )
    if not arquivos:
        raise ErroDataset(f"Nenhuma imagem encontrada em {pasta_imagens}.")

    resumo = ResumoCarregamento(amostras=[], formato="yolo")
    for caminho in arquivos:
        if limite is not None and len(resumo.amostras) >= limite:
            break
        arquivo_rotulo = pasta_rotulos / f"{caminho.stem}.txt"
        anotacoes: list[Anotacao] = []
        if arquivo_rotulo.is_file():
            largura, altura = _dimensoes(caminho)
            for linha in arquivo_rotulo.read_text(encoding="utf-8").splitlines():
                campos = linha.split()
                if len(campos) < 5:
                    continue
                indice = int(float(campos[0]))
                if indice >= len(nomes_classes):
                    continue
                classe = converter_rotulo(nomes_classes[indice])
                if classe is None:
                    chave = nomes_classes[indice].strip().lower()
                    resumo.anotacoes_excluidas[chave] = (
                        resumo.anotacoes_excluidas.get(chave, 0) + 1
                    )
                    continue
                cx, cy, largura_rel, altura_rel = (float(v) for v in campos[1:5])
                meia_largura = largura_rel * largura / 2
                meia_altura = altura_rel * altura / 2
                centro_x = cx * largura
                centro_y = cy * altura
                anotacoes.append(
                    Anotacao(
                        classe=classe,
                        caixa=Caixa(
                            centro_x - meia_largura,
                            centro_y - meia_altura,
                            centro_x + meia_largura,
                            centro_y + meia_altura,
                        ),
                    )
                )
                resumo.anotacoes_aproveitadas += 1
        resumo.amostras.append(Amostra(caminho=caminho, anotacoes=anotacoes))
    return resumo


# ------------------------------------------------------------ despacho
def carregar(
    pasta_imagens: Path,
    arquivo_rotulos: Path | None = None,
    pasta_rotulos: Path | None = None,
    arquivo_classes: Path | None = None,
    limite: int | None = None,
) -> ResumoCarregamento:
    """Carrega o conjunto de avaliação detectando o formato automaticamente."""
    if not pasta_imagens.is_dir():
        raise ErroDataset(f"Pasta de imagens não encontrada: {pasta_imagens}")

    # Formato Supervisely: a pasta informada contém 'ann' e 'img'.
    if (pasta_imagens / "ann").is_dir() and _pasta_de_imagens(pasta_imagens):
        return carregar_supervisely(pasta_imagens, limite)
    # Tolerância: a pasta informada é a de imagens, e 'ann' está ao lado.
    if pasta_imagens.name in {"img", "images", "image"} and (
        pasta_imagens.parent / "ann"
    ).is_dir():
        return carregar_supervisely(pasta_imagens.parent, limite)

    if arquivo_rotulos is not None:
        if not arquivo_rotulos.is_file():
            raise ErroDataset(f"Arquivo de rótulos não encontrado: {arquivo_rotulos}")
        return carregar_bdd100k(arquivo_rotulos, pasta_imagens, limite)

    if pasta_rotulos is None:
        candidata = pasta_imagens.parent / "labels"
        pasta_rotulos = candidata if candidata.is_dir() else pasta_imagens
    if arquivo_classes is None:
        for candidato in ("data.yaml", "classes.txt"):
            possivel = pasta_rotulos.parent / candidato
            if possivel.is_file():
                arquivo_classes = possivel
                break
    if arquivo_classes is None:
        raise ErroDataset(
            "Informe --classes com o data.yaml ou classes.txt do conjunto, ou "
            "use --rotulos para o arquivo JSON do BDD100K."
        )

    if arquivo_classes.suffix == ".yaml":
        nomes = _nomes_do_data_yaml(arquivo_classes)
    else:
        nomes = [
            linha.strip()
            for linha in arquivo_classes.read_text(encoding="utf-8").splitlines()
            if linha.strip()
        ]
    if not nomes:
        raise ErroDataset(f"Não foi possível ler nomes de classe de {arquivo_classes}.")
    return carregar_yolo(pasta_imagens, pasta_rotulos, nomes, limite)
