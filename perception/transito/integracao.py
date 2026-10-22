import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from transito.application import KNOWLEDGE_BASE_ROOT, KnowledgeBase
from transito.client import Settings, TypeDBClient, TypeDBError

CLASS_TO_TYPE = {"carro": "carro", "moto": "moto", "caminhão": "caminhao"}
TYPES_QUERY = KNOWLEDGE_BASE_ROOT / "consultas" / "07-tipos-de-veiculo.tql"


def count_classes(report: dict[str, Any]) -> Counter[str]:
    if "objetos_rastreados" in report:
        return Counter(item["classe"] for item in report["objetos_rastreados"].values())
    if "deteccoes" in report:
        return Counter(item["classe"] for item in report["deteccoes"])
    raise ValueError("O arquivo não é um relatório gerado por visao.py.")


def match_types(report: dict[str, Any], known_types: set[str]) -> dict[str, Any]:
    matched: dict[str, int] = {}
    unmatched: dict[str, int] = {}
    for name, amount in sorted(count_classes(report).items()):
        kind = CLASS_TO_TYPE.get(name)
        if kind in known_types:
            matched[kind] = amount
        else:
            unmatched[name] = amount
    return {
        "relatorio": report.get("arquivo"),
        "tipos_na_base": matched,
        "sem_correspondencia": unmatched,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Cruza um relatório da visão com os tipos de veículo da base TypeDB."
    )
    parser.add_argument("relatorio", type=Path)
    parser.add_argument("--url", default="http://127.0.0.1:18000")
    parser.add_argument("--database", default="transito")
    args = parser.parse_args(argv)
    output = args.relatorio.with_name(f"{args.relatorio.stem}_integracao.json")
    try:
        report = json.loads(args.relatorio.read_text(encoding="utf-8"))
        client = TypeDBClient(
            Settings(
                url=args.url,
                database=args.database,
                username=os.environ.get("TYPEDB_USER", "admin"),
                password=os.environ.get("TYPEDB_PASSWORD", "password"),
            )
        )
        client.connect()
        types = {item["tipo"] for item in client.query(KnowledgeBase.read(TYPES_QUERY))}
        result = match_types(report, types)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (TypeDBError, OSError, ValueError, KeyError) as error:
        print(f"Erro: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
