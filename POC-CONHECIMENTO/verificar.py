"""Verificacao das questoes de competencia da base de conhecimento.

Cada questao e formulada como consulta e confrontada com a resposta esperada,
definida antes da modelagem. A verificacao considera tanto o que a base deve
devolver quanto o que ela nao deve, pois e o par negativo que distingue uma
base que raciocina de uma que apenas devolve o que foi inserido.

Uso:
    python verificar.py
    python verificar.py --saida resultados
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))

from setup_poc import ENDERECO_PADRAO  # noqa: E402
from setup_poc import BANCO_PADRAO, SENHA_PADRAO, USUARIO_PADRAO  # noqa: E402
from setup_poc import ErroSetup, abrir_driver  # noqa: E402


@dataclass
class QuestaoDeCompetencia:
    """Pergunta que a base deve ser capaz de responder."""

    codigo: str
    capacidade: str
    enunciado: str
    consulta: str
    variavel: str
    esperado: set[str]
    # Identificadores que nao podem figurar na resposta. Quando vazio, a
    # verificacao exige igualdade exata com o conjunto esperado.
    proibido: set[str] = field(default_factory=set)


# ---------------------------------------------------------------------
# Questoes de competencia
# ---------------------------------------------------------------------

QUESTOES = [
    # ---- capacidade 1: hierarquia e composicao ----------------------
    QuestaoDeCompetencia(
        codigo="QC01",
        capacidade="Hierarquia de tipos",
        enunciado=(
            "Uma consulta pelo tipo geral veiculo alcanca todas as suas "
            "especializacoes sem enumera-las?"
        ),
        consulta=(
            "match $v isa veiculo, has identificador $id;"
            ' $id like "c12_.*"; select $id;'
        ),
        variavel="id",
        esperado={
            "c12_automovel",
            "c12_motocicleta",
            "c12_onibus",
            "c12_caminhao",
            "c12_bicicleta",
        },
    ),
    QuestaoDeCompetencia(
        codigo="QC02",
        capacidade="Hierarquia de tipos",
        enunciado=(
            "A bicicleta figura como veiculo, conforme o CTB, e nao como "
            "objeto a parte?"
        ),
        consulta=(
            "match $v isa veiculo, has identificador $id;"
            ' $id == "c12_bicicleta"; select $id;'
        ),
        variavel="id",
        esperado={"c12_bicicleta"},
    ),
    QuestaoDeCompetencia(
        codigo="QC03",
        capacidade="Categoria derivada",
        enunciado=(
            "A categoria de motociclista e derivada da conducao de uma "
            "motocicleta, sem ser declarada como tipo?"
        ),
        consulta=(
            "match let $p in motociclistas();"
            " $p has identificador $id; select $id;"
        ),
        variavel="id",
        esperado={"c09_condutor", "c10_condutor"},
        proibido={"c11_condutor"},
    ),
    QuestaoDeCompetencia(
        codigo="QC04",
        capacidade="Categoria derivada",
        enunciado=(
            "A pessoa que conduz bicicleta e reconhecida como ciclista e "
            "nao como motociclista?"
        ),
        consulta=(
            "match let $p in ciclistas();"
            " $p has identificador $id; select $id;"
        ),
        variavel="id",
        esperado={"c11_condutor"},
    ),
    # ---- capacidade 2: relacoes n-arias ------------------------------
    QuestaoDeCompetencia(
        codigo="QC05",
        capacidade="Relacao n-aria",
        enunciado=(
            "Dada uma ultrapassagem, a base devolve os tres participantes "
            "com seus papeis distintos?"
        ),
        consulta=(
            "match $m isa ultrapassagem,"
            ' has identificador "m07_ultrapassagem_direita";'
            " $m links (ultrapassante: $a, ultrapassado: $b,"
            " faixa_utilizada: $f);"
            " $a has identificador $id; select $id;"
        ),
        variavel="id",
        esperado={"c07_ultrapassante"},
    ),
    QuestaoDeCompetencia(
        codigo="QC06",
        capacidade="Relacao n-aria",
        enunciado=(
            "A mudanca de faixa registra as faixas de origem e destino e a "
            "marcacao transposta em uma unica relacao?"
        ),
        consulta=(
            "match $m isa mudanca_de_faixa,"
            ' has identificador "m03_mudanca_continua";'
            " $m links (faixa_de_origem: $o, faixa_de_destino: $d,"
            " marcacao_transposta: $mar);"
            " $mar has identificador $id; select $id;"
        ),
        variavel="id",
        esperado={"c03_marcacao"},
    ),
    QuestaoDeCompetencia(
        codigo="QC07",
        capacidade="Relacao n-aria",
        enunciado=(
            "Uma consulta pelo papel de executor alcanca manobras de "
            "subtipos distintos?"
        ),
        consulta=(
            "match $m isa manobra, links (executor: $v);"
            ' $v has identificador "c03_carro";'
            " $m has identificador $id; select $id;"
        ),
        variavel="id",
        esperado={"m03_mudanca_continua"},
    ),
    # ---- capacidade 3: caracterizacao normativa ----------------------
    QuestaoDeCompetencia(
        codigo="QC08",
        capacidade="Caracterizacao normativa",
        enunciado=(
            "A transposicao de cruzamento com semaforo vermelho e "
            "caracterizada, e a com semaforo verde nao?"
        ),
        consulta=(
            "match let $m in avancos_de_sinal_vermelho();"
            " $m has identificador $id; select $id;"
        ),
        variavel="id",
        esperado={"m01_avanco_vermelho"},
        proibido={"m02_transposicao_verde"},
    ),
    QuestaoDeCompetencia(
        codigo="QC09",
        capacidade="Caracterizacao normativa",
        enunciado=(
            "A mudanca de faixa sobre marcacao continua e caracterizada, e "
            "a sobre marcacao tracejada nao?"
        ),
        consulta=(
            "match let $m in mudancas_sobre_linha_continua();"
            " $m has identificador $id; select $id;"
        ),
        variavel="id",
        esperado={"m03_mudanca_continua"},
        proibido={"m04_mudanca_tracejada"},
    ),
    QuestaoDeCompetencia(
        codigo="QC10",
        capacidade="Caracterizacao normativa",
        enunciado=(
            "A mudanca de faixa sem sinalizacao previa e caracterizada, e a "
            "precedida de sinalizacao para o mesmo lado nao?"
        ),
        consulta=(
            "match let $m in mudancas_sem_sinalizacao();"
            " $m has identificador $id; select $id;"
        ),
        variavel="id",
        esperado={"m03_mudanca_continua", "m05_mudanca_sem_seta"},
        proibido={"m04_mudanca_tracejada", "m06_mudanca_com_seta"},
    ),
    QuestaoDeCompetencia(
        codigo="QC11",
        capacidade="Caracterizacao normativa",
        enunciado=(
            "A ultrapassagem pela direita e caracterizada, e a pela "
            "esquerda, que o CTB prescreve, nao?"
        ),
        consulta=(
            "match let $m in ultrapassagens_pela_direita();"
            " $m has identificador $id; select $id;"
        ),
        variavel="id",
        esperado={"m07_ultrapassagem_direita"},
        proibido={"m08_ultrapassagem_esquerda"},
    ),
    QuestaoDeCompetencia(
        codigo="QC12",
        capacidade="Caracterizacao normativa",
        enunciado=(
            "O condutor de motocicleta sem capacete e caracterizado, e o "
            "que porta capacete nao?"
        ),
        consulta=(
            "match let $p in condutores_sem_capacete();"
            " $p has identificador $id; select $id;"
        ),
        variavel="id",
        esperado={"c09_condutor"},
        proibido={"c10_condutor"},
    ),
    QuestaoDeCompetencia(
        codigo="QC13",
        capacidade="Catalogo normativo",
        enunciado=(
            "O catalogo distingue as condutas do ramo normativo das do "
            "ramo de risco?"
        ),
        consulta=(
            'match $c isa conduta_tipificada, has ramo "risco",'
            " has identificador $id; select $id;"
        ),
        variavel="id",
        esperado={"aproximacao_critica", "ultrapassagem_com_folga_reduzida"},
    ),
]


# ---------------------------------------------------------------------
# Execucao
# ---------------------------------------------------------------------


def executar(td, driver, banco: str, questao: QuestaoDeCompetencia) -> dict:
    """Executa uma questao e compara a resposta com a esperada."""
    registro = {
        "codigo": questao.codigo,
        "capacidade": questao.capacidade,
        "enunciado": questao.enunciado,
        "consulta": questao.consulta,
        "esperado": sorted(questao.esperado),
        "proibido": sorted(questao.proibido),
    }
    try:
        with driver.transaction(banco, td.TransactionType.READ) as transacao:
            resposta = transacao.query(questao.consulta).resolve()
            obtido = set()
            for linha in resposta.as_concept_rows():
                conceito = linha.get(questao.variavel)
                valor = (
                    conceito.get_value()
                    if hasattr(conceito, "get_value")
                    else conceito
                )
                obtido.add(str(valor))
    except Exception as erro:  # noqa: BLE001
        registro.update(
            {"obtido": [], "situacao": "erro", "detalhe": str(erro)[:400]}
        )
        return registro

    faltando = questao.esperado - obtido
    indevidos = (obtido & questao.proibido) | (
        obtido - questao.esperado if not questao.proibido else set()
    )

    if not faltando and not indevidos:
        situacao, detalhe = "atendida", ""
    elif faltando and indevidos:
        situacao = "nao atendida"
        detalhe = (
            f"faltaram {sorted(faltando)}; indevidos {sorted(indevidos)}"
        )
    elif faltando:
        situacao, detalhe = "nao atendida", f"faltaram {sorted(faltando)}"
    else:
        situacao, detalhe = "nao atendida", f"indevidos {sorted(indevidos)}"

    registro.update(
        {"obtido": sorted(obtido), "situacao": situacao, "detalhe": detalhe}
    )
    return registro


def imprimir(registros: list[dict]) -> None:
    largura = 84
    print("\n" + "=" * largura)
    print("VERIFICACAO DAS QUESTOES DE COMPETENCIA")
    print("=" * largura)

    capacidade_atual = ""
    for registro in registros:
        if registro["capacidade"] != capacidade_atual:
            capacidade_atual = registro["capacidade"]
            print(f"\n{capacidade_atual}")
            print("-" * largura)
        marca = {
            "atendida": "  OK  ",
            "nao atendida": " FALHA",
            "erro": " ERRO ",
        }[registro["situacao"]]
        print(f"{marca} {registro['codigo']}  {registro['enunciado']}")
        if registro["situacao"] != "atendida":
            print(f"         esperado: {registro['esperado']}")
            print(f"         obtido:   {registro['obtido']}")
            if registro["detalhe"]:
                print(f"         {registro['detalhe']}")

    atendidas = sum(1 for r in registros if r["situacao"] == "atendida")
    print("\n" + "=" * largura)
    print(f"{atendidas} de {len(registros)} questoes atendidas")
    print("=" * largura)


SITUACAO_POR_EXTENSO = {
    "atendida": "Atendida",
    "nao atendida": "Não atendida",
    "erro": "Erro de execução",
}


def escapar_tex(texto: str) -> str:
    """Neutraliza os caracteres que o LaTeX interpreta como comando."""
    substituicoes = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    for alvo, troca in substituicoes.items():
        texto = texto.replace(alvo, troca)
    return texto


def gravar_tex(registros: list[dict], caminho: Path) -> None:
    """Gera a tabela pronta para inclusao no texto do trabalho."""
    atendidas = sum(1 for r in registros if r["situacao"] == "atendida")
    total = len(registros)

    linhas = [
        "% Gerado por verificar.py. Inclua no texto com \\input{...}.",
        "% Requer os pacotes longtable e booktabs.",
        "\\begin{longtable}{@{}p{1.4cm}p{9.8cm}p{3.0cm}@{}}",
        "\\caption{Verificação das questões de competência da base de "
        "conhecimento}",
        "\\label{quad:questoes-de-competencia}\\\\",
        "\\toprule",
        "\\textbf{ID} & \\textbf{Questão de competência} & "
        "\\textbf{Resultado} \\\\",
        "\\midrule",
        "\\endfirsthead",
        "",
        "\\multicolumn{3}{@{}l}{\\small Quadro "
        "\\ref{quad:questoes-de-competencia} -- continuação} \\\\",
        "\\toprule",
        "\\textbf{ID} & \\textbf{Questão de competência} & "
        "\\textbf{Resultado} \\\\",
        "\\midrule",
        "\\endhead",
        "",
        "\\midrule",
        "\\multicolumn{3}{r@{}}{\\small Continua na próxima página} \\\\",
        "\\endfoot",
        "",
        "\\bottomrule",
        "\\endlastfoot",
        "",
    ]

    capacidade_atual = ""
    for registro in registros:
        if registro["capacidade"] != capacidade_atual:
            if capacidade_atual:
                linhas.append("\\midrule")
            capacidade_atual = registro["capacidade"]
            linhas.append(
                f"\\multicolumn{{3}}{{@{{}}l}}{{\\textit{{"
                f"{escapar_tex(capacidade_atual)}}}}} \\\\"
            )
            linhas.append("\\midrule")
        linhas.append(
            f"{escapar_tex(registro['codigo'])} & "
            f"{escapar_tex(registro['enunciado'])} & "
            f"{SITUACAO_POR_EXTENSO[registro['situacao']]} \\\\"
        )

    linhas.append("")
    linhas.append("\\end{longtable}")
    linhas.append("")
    linhas.append(
        f"% Resumo: {atendidas} de {total} questões atendidas."
    )

    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")


def gravar_detalhamento_tex(registros: list[dict], caminho: Path) -> None:
    """Gera a tabela das questoes nao atendidas, com o que se esperava.

    Produzida apenas quando ha falhas, pois o que nao funcionou constitui
    resultado tanto quanto o que funcionou.
    """
    falhas = [r for r in registros if r["situacao"] != "atendida"]
    if not falhas:
        caminho.write_text(
            "% Nenhuma questão de competência deixou de ser atendida.\n",
            encoding="utf-8",
        )
        return

    linhas = [
        "% Gerado por verificar.py. Inclua no texto com \\input{...}.",
        "\\begin{longtable}{@{}p{1.4cm}p{5.5cm}p{3.4cm}p{3.4cm}@{}}",
        "\\caption{Questões de competência não atendidas}",
        "\\label{quad:questoes-nao-atendidas}\\\\",
        "\\toprule",
        "\\textbf{ID} & \\textbf{Questão} & \\textbf{Esperado} & "
        "\\textbf{Obtido} \\\\",
        "\\midrule",
        "\\endfirsthead",
        "\\toprule",
        "\\textbf{ID} & \\textbf{Questão} & \\textbf{Esperado} & "
        "\\textbf{Obtido} \\\\",
        "\\midrule",
        "\\endhead",
        "\\bottomrule",
        "\\endlastfoot",
        "",
    ]
    for registro in falhas:
        esperado = ", ".join(registro["esperado"]) or "---"
        obtido = ", ".join(registro["obtido"]) or "nenhum"
        linhas.append(
            f"{escapar_tex(registro['codigo'])} & "
            f"{escapar_tex(registro['enunciado'])} & "
            f"\\texttt{{\\footnotesize {escapar_tex(esperado)}}} & "
            f"\\texttt{{\\footnotesize {escapar_tex(obtido)}}} \\\\"
        )
    linhas.append("")
    linhas.append("\\end{longtable}")

    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")


def gravar(registros: list[dict], pasta: Path) -> None:
    pasta.mkdir(parents=True, exist_ok=True)

    (pasta / "questoes-de-competencia.json").write_text(
        json.dumps(
            {
                "executado_em": datetime.now(timezone.utc).isoformat(
                    timespec="seconds"
                ),
                "total": len(registros),
                "atendidas": sum(
                    1 for r in registros if r["situacao"] == "atendida"
                ),
                "questoes": registros,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    with (pasta / "questoes-de-competencia.csv").open(
        "w", encoding="utf-8", newline=""
    ) as arquivo:
        escritor = csv.writer(arquivo)
        escritor.writerow(
            ["codigo", "capacidade", "enunciado", "situacao", "detalhe"]
        )
        for registro in registros:
            escritor.writerow(
                [
                    registro["codigo"],
                    registro["capacidade"],
                    registro["enunciado"],
                    registro["situacao"],
                    registro["detalhe"],
                ]
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endereco", default=ENDERECO_PADRAO)
    parser.add_argument("--usuario", default=USUARIO_PADRAO)
    parser.add_argument("--senha", default=SENHA_PADRAO)
    parser.add_argument("--banco", default=BANCO_PADRAO)
    parser.add_argument("--saida", type=Path, default=RAIZ / "resultados")
    args = parser.parse_args(argv)

    try:
        td, driver = abrir_driver(args.endereco, args.usuario, args.senha)
    except ErroSetup as erro:
        print(f"Erro: {erro}", file=sys.stderr)
        return 1

    with driver:
        registros = [
            executar(td, driver, args.banco, questao) for questao in QUESTOES
        ]

    imprimir(registros)
    gravar(registros, args.saida)
    print(f"\nRelatorio: {args.saida / 'questoes-de-competencia.json'}")
    print(f"Planilha:  {args.saida / 'questoes-de-competencia.csv'}")

    return 0 if all(r["situacao"] == "atendida" for r in registros) else 2


if __name__ == "__main__":
    raise SystemExit(main())