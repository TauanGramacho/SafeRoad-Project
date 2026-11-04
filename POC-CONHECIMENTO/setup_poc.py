"""Prepara a base de conhecimento da segunda prova de conceito.

Sobe o servidor TypeDB, cria o banco de dados, carrega o esquema, as funcoes
de inferencia e o catalogo de condutas tipificadas, e verifica o resultado.

Uso:
    python setup_poc.py                 # sobe o container e carrega tudo
    python setup_poc.py --recriar       # apaga o banco antes de carregar
    python setup_poc.py --sem-docker    # usa um servidor ja em execucao
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent

ENDERECO_PADRAO = "localhost:1729"
USUARIO_PADRAO = "admin"
SENHA_PADRAO = "password"
BANCO_PADRAO = "saferoad"
BASE = "database/"

# Ordem de carga: o esquema precede as funcoes, que precedem os dados.
ARQUIVOS = [
    (BASE+"schema.tql", "schema", "esquema"),
    (BASE+"funcoes.tql", "schema", "funcoes de inferencia"),
    (BASE+"catalogo.tql", "write", "catalogo de condutas"),
]


class ErroSetup(Exception):
    pass


# ---------------------------------------------------------------- docker
def docker_disponivel() -> bool:
    return shutil.which("docker") is not None


def subir_container() -> None:
    """Sobe o servidor TypeDB por docker compose."""
    if not docker_disponivel():
        raise ErroSetup(
            "Docker nao encontrado. Suba o TypeDB manualmente e use "
            "--sem-docker, ou instale o Docker."
        )
    compose = RAIZ / "compose.yaml"
    if not compose.is_file():
        raise ErroSetup(f"Arquivo nao encontrado: {compose}")

    print("Subindo o servidor TypeDB...")
    resultado = subprocess.run(
        ["docker", "compose", "-f", str(compose), "up", "-d"],
        capture_output=True,
        text=True,
    )
    if resultado.returncode != 0:
        raise ErroSetup(
            "Falha ao subir o container:\n"
            f"{resultado.stderr.strip() or resultado.stdout.strip()}"
        )
    print("  container em execucao")


# ---------------------------------------------------------------- driver
def abrir_driver(endereco: str, usuario: str, senha: str):
    """Abre a conexao, tolerando as duas assinaturas de DriverOptions.

    A forma do parametro de TLS mudou entre versoes 3.x do driver; ambas sao
    tentadas para que o script funcione sem exigir uma versao especifica.
    """
    try:
        import typedb.driver as td
    except ImportError as erro:
        raise ErroSetup(
            "Driver do TypeDB nao encontrado. Instale com "
            "'pip install typedb-driver'."
        ) from erro

    credenciais = td.Credentials(usuario, senha)

    tentativas = []
    if hasattr(td, "DriverTlsConfig"):
        tentativas.append(
            lambda: td.DriverOptions(td.DriverTlsConfig.disabled())
        )
    tentativas.append(lambda: td.DriverOptions(False, None))
    tentativas.append(lambda: td.DriverOptions())

    ultimo_erro: Exception | None = None
    for construir in tentativas:
        try:
            opcoes = construir()
        except TypeError as erro:
            ultimo_erro = erro
            continue
        try:
            return td, td.TypeDB.driver(endereco, credenciais, opcoes)
        except Exception as erro:  # noqa: BLE001
            ultimo_erro = erro
            continue
    raise ErroSetup(f"Nao foi possivel abrir a conexao: {ultimo_erro}")


def aguardar_servidor(
    endereco: str, usuario: str, senha: str, segundos: int = 60
):
    """Tenta conectar repetidamente ate o servidor aceitar conexoes."""
    print(f"Aguardando o servidor em {endereco}...")
    limite = time.monotonic() + segundos
    ultimo_erro: Exception | None = None
    while time.monotonic() < limite:
        try:
            td, driver = abrir_driver(endereco, usuario, senha)
            print("  servidor disponivel")
            return td, driver
        except ErroSetup as erro:
            if "Driver do TypeDB nao encontrado" in str(erro):
                raise
            ultimo_erro = erro
            time.sleep(2)
    raise ErroSetup(
        f"O servidor nao respondeu em {segundos} s. Ultimo erro: {ultimo_erro}"
    )


# ------------------------------------------------------------------ carga
def preparar_banco(driver, banco: str, recriar: bool) -> None:
    existe = driver.databases.contains(banco)
    if existe and recriar:
        print(f"Apagando o banco '{banco}'...")
        driver.databases.get(banco).delete()
        existe = False
    if existe:
        print(f"Banco '{banco}' ja existe. Use --recriar para refaze-lo.")
        return
    print(f"Criando o banco '{banco}'...")
    driver.databases.create(banco)


def carregar_arquivo(td, driver, banco: str, caminho: Path, tipo: str) -> None:
    conteudo = caminho.read_text(encoding="utf-8")
    # Um arquivo corresponde a uma unica consulta: o bloco define ou insert.
    if not conteudo.strip():
        raise ErroSetup(f"Arquivo vazio: {caminho}")

    tipo_transacao = {
        "schema": td.TransactionType.SCHEMA,
        "write": td.TransactionType.WRITE,
        "read": td.TransactionType.READ,
    }[tipo]

    with driver.transaction(banco, tipo_transacao) as transacao:
        transacao.query(conteudo).resolve()
        transacao.commit()


def consultar(td, driver, banco: str, consulta: str) -> list:
    with driver.transaction(banco, td.TransactionType.READ) as transacao:
        resposta = transacao.query(consulta).resolve()
        return list(resposta.as_concept_rows())


# ------------------------------------------------------------ verificacao
def verificar(td, driver, banco: str) -> None:
    """Confere que esquema, funcoes e dados foram de fato carregados."""
    print("\nVerificando a carga:")

    condutas = consultar(
        td,
        driver,
        banco,
        "match $c isa conduta_tipificada, has identificador $i; select $i;",
    )
    print(f"  condutas tipificadas carregadas: {len(condutas)}")

    normativas = consultar(
        td,
        driver,
        banco,
        'match $c isa conduta_tipificada, has ramo "normativo",'
        " has identificador $i; select $i;",
    )
    risco = consultar(
        td,
        driver,
        banco,
        'match $c isa conduta_tipificada, has ramo "risco",'
        " has identificador $i; select $i;",
    )
    print(f"    ramo normativo: {len(normativas)}")
    print(f"    ramo de risco:  {len(risco)}")

    # A chamada a uma funcao confirma que as definicoes foram aceitas.
    # Sem cenas carregadas, o resultado esperado e vazio.
    try:
        consultar(td, driver, banco, "match $p in motociclistas(); select $p;")
        print("  funcoes de inferencia: definidas e executaveis")
    except Exception as erro:  # noqa: BLE001
        print(f"  funcoes de inferencia: FALHA ao executar -> {erro}")

    if len(condutas) == 0:
        print(
            "\nAtencao: nenhuma conduta foi carregada. Verifique o "
            "catalogo.tql."
        )


# -------------------------------------------------------------------- cli
def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepara a base de conhecimento da prova de conceito.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--endereco", default=ENDERECO_PADRAO)
    parser.add_argument("--usuario", default=USUARIO_PADRAO)
    parser.add_argument("--senha", default=SENHA_PADRAO)
    parser.add_argument("--banco", default=BANCO_PADRAO)
    parser.add_argument(
        "--recriar",
        action="store_true",
        help="Apaga o banco antes de carregar, garantindo estado limpo.",
    )
    parser.add_argument(
        "--sem-docker",
        action="store_true",
        help="Nao gerencia o container; usa um servidor ja em execucao.",
    )
    parser.add_argument(
        "--espera",
        type=int,
        default=60,
        help="Segundos de espera pelo servidor.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)

    try:
        faltando = [
            nome for nome, _, _ in ARQUIVOS if not (RAIZ / nome).is_file()
        ]
        if faltando:
            raise ErroSetup(
                "Arquivos ausentes na pasta do script: " + ", ".join(faltando)
            )

        if not args.sem_docker:
            subir_container()

        td, driver = aguardar_servidor(
            args.endereco, args.usuario, args.senha, args.espera
        )

        with driver:
            preparar_banco(driver, args.banco, args.recriar)

            print("\nCarregando:")
            for nome, tipo, descricao in ARQUIVOS:
                caminho = RAIZ / nome
                print(f"  {descricao} ({nome})...", end=" ", flush=True)
                try:
                    carregar_arquivo(td, driver, args.banco, caminho, tipo)
                except Exception as erro:  # noqa: BLE001
                    print("FALHA")
                    raise ErroSetup(
                        f"Erro ao carregar {nome}:\n  {erro}\n\n"
                        "A carga e interrompida aqui, pois os arquivos "
                        "seguintes dependem deste."
                    ) from erro
                print("ok")

            verificar(td, driver, args.banco)

        print(f"\nBase '{args.banco}' pronta em {args.endereco}.")
        print("Proximo passo: carregar as cenas e executar as consultas de")
        print("competencia.")

    except ErroSetup as erro:
        print(f"\nErro: {erro}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrompido.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
