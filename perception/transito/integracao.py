import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from transito import visao
from transito.application import KnowledgeBase
from transito.client import Document, Settings, TypeDBClient, TypeDBError

DEFAULT_DATABASE = "roadguard"
# Classes sem tipo próprio na ontologia (ônibus, bicicleta) viram objeto-generico.
TYPE_BY_CLASS = {
    "pessoa": "pessoa",
    "carro": "carro",
    "moto": "moto",
    "caminhão": "caminhao",
    "semáforo": "semaforo",
    "placa de pare": "placa-pare",
}
GENERIC_TYPE = "objeto-generico"
VEHICLE_TYPES = {"carro", "moto", "caminhao"}
SIGNAL_TYPES = {"semaforo", "placa-pare"}
LABEL_BY_TYPE = {
    "pessoa": "Pessoa observada",
    "carro": "Carro observado",
    "moto": "Moto observada",
    "caminhao": "Caminhão observado",
}


class IngestionError(Exception):
    pass


def tql_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def tql_double(value: float) -> str:
    return f"{float(value):.6f}"


def analysis_code(report: dict[str, Any]) -> str:
    canonical = json.dumps(report, ensure_ascii=False, sort_keys=True)
    return "A-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def media_kind(report: dict[str, Any]) -> str:
    if "objetos_rastreados" in report:
        return "video"
    if "deteccoes" in report:
        return "imagem"
    raise IngestionError("O relatório não é de imagem nem de vídeo.")


def observed_objects(report: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    if kind == "imagem":
        return [
            {
                "ref": f"D{index}",
                "rotulo": f"(detecção {index})",
                "classe": item["classe"],
                "confianca": item["confianca"],
                "id_rastreamento": None,
                "quadros": None,
                "posicao": item.get("posicao_no_quadro"),
                "faixa": (item.get("faixa_estimada") or {}).get("posicao"),
            }
            for index, item in enumerate(report["deteccoes"])
        ]
    return [
        {
            "ref": f"T{int(track_id)}",
            "rotulo": f"#{int(track_id)}",
            "classe": item["classe"],
            "confianca": item["confianca_maxima"],
            "id_rastreamento": int(track_id),
            "quadros": item["quadros_detectados"],
            "posicao": item.get("ultima_posicao_no_quadro"),
            "faixa": item.get("ultima_faixa_estimada"),
        }
        for track_id, item in sorted(report["objetos_rastreados"].items(), key=lambda i: int(i[0]))
    ]


def build_insert(report: dict[str, Any], code: str) -> tuple[str, dict[str, int]]:
    try:
        return _build_insert(report, code)
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise IngestionError("O relatório não possui a estrutura esperada.") from error


def _build_insert(report: dict[str, Any], code: str) -> tuple[str, dict[str, int]]:
    kind = media_kind(report)
    lines = [
        "insert",
        f"$a isa analise, has codigo {tql_string(code)}, "
        f"has arquivo {tql_string(str(report['arquivo']))}, "
        f"has tipo-midia {tql_string(kind)}, "
        f"has modelo-deteccao {tql_string(str(report['modelo']))};",
    ]
    summary = {"objetos": 0, "conducoes": 0, "passagens_por_sinal": 0, "ignorados": 0}
    variables: dict[str, tuple[str, str]] = {}
    for number, item in enumerate(observed_objects(report, kind)):
        kb_type = TYPE_BY_CLASS.get(item["classe"], GENERIC_TYPE)
        variable = f"$o{number}"
        variables[item["ref"]] = (variable, kb_type)
        object_code = f"{code}-{item['ref']}"
        entity = f"{variable} isa {kb_type}, has codigo {tql_string(object_code)}"
        label = f"{LABEL_BY_TYPE.get(kb_type, '')} {item['rotulo']}"
        if kb_type == "pessoa":
            entity += f", has nome {tql_string(label)}"
        elif kb_type in VEHICLE_TYPES:
            entity += f", has modelo {tql_string(label)}"
        elif kb_type == GENERIC_TYPE:
            entity += f", has classe-detectada {tql_string(item['classe'])}"
        lines.append(entity + ";")
        record = (
            f"$r{number} isa registro-visual, links (origem: $a, objeto: {variable}), "
            f"has classe-detectada {tql_string(item['classe'])}, "
            f"has confianca {tql_double(item['confianca'])}"
        )
        if item["id_rastreamento"] is not None:
            record += f", has id-rastreamento {int(item['id_rastreamento'])}"
        if item["quadros"] is not None:
            record += f", has quadros-detectados {int(item['quadros'])}"
        if item["posicao"]:
            record += f", has posicao-no-quadro {tql_string(item['posicao'])}"
        if item["faixa"]:
            record += f", has faixa-estimada {tql_string(item['faixa'])}"
        lines.append(record + ";")
        summary["objetos"] += 1

    def lookup(ref: str) -> tuple[str, str]:
        if ref not in variables:
            raise IngestionError(f"O relatório cita o objeto {ref}, que não foi detectado.")
        return variables[ref]

    for association in report.get("associacoes", []):
        if association["tipo"] != "possivel_conducao":
            continue
        if kind == "imagem":
            refs = (f"D{association['indice_pessoa']}", f"D{association['indice_veiculo']}")
        else:
            refs = (f"T{association['id_pessoa']}", f"T{association['id_veiculo']}")
        (person, person_type), (vehicle, vehicle_type) = lookup(refs[0]), lookup(refs[1])
        # O rastreador pode trocar a classe de um ID; nesse caso o vínculo é descartado.
        if person_type != "pessoa" or vehicle_type not in VEHICLE_TYPES:
            summary["ignorados"] += 1
            continue
        lines.append(f"conducao (condutor: {person}, veiculo-conduzido: {vehicle});")
        summary["conducoes"] += 1

    for number, event in enumerate(report.get("eventos", [])):
        if event["tipo"] != "possivel_passagem_visual_por_sinal":
            continue
        vehicle, vehicle_type = lookup(f"T{event['id_rastreamento']}")
        signal_type = TYPE_BY_CLASS.get(event["sinal"])
        if vehicle_type not in VEHICLE_TYPES or signal_type not in SIGNAL_TYPES:
            summary["ignorados"] += 1
            continue
        signal_id = event.get("id_rastreamento_sinal")
        if signal_id is not None and f"T{signal_id}" in variables:
            signal = variables[f"T{signal_id}"][0]
        else:
            signal = f"$s{number}"
            lines.append(
                f"{signal} isa {signal_type}, has codigo {tql_string(f'{code}-E{number}')};"
            )
        lines.append(
            f"$e{number} isa passagem-por-sinal, "
            f"links (veiculo-passante: {vehicle}, sinal-cruzado: {signal}), "
            f"has quadro {int(event['quadro'])}, has tempo-s {tql_double(event['tempo_s'])};"
        )
        summary["passagens_por_sinal"] += 1
    return "\n".join(lines), summary


class ObservationStore:
    def __init__(self, client: TypeDBClient) -> None:
        self.client = client

    def register(self, report: dict[str, Any]) -> tuple[str, dict[str, int] | None]:
        code = analysis_code(report)
        exists = self.client.query(
            f'match $a isa analise, has codigo {tql_string(code)}; fetch {{"codigo": $a.codigo}};'
        )
        if exists:
            return code, None
        query, summary = build_insert(report, code)
        self.client.query(query, "write")
        return code, summary

    def findings(self, code: str) -> dict[str, list[Document]]:
        analysis = f"$a isa analise, has codigo {tql_string(code)};"
        return {
            "objetos": self.client.query(
                f"match {analysis} "
                "$r isa registro-visual, links (origem: $a, objeto: $o); "
                "$o isa! $tipo, has codigo $codigo; sort $codigo; "
                'fetch {"codigo": $codigo, "tipo": label($tipo), '
                '"classe": $r.classe-detectada, "confianca": $r.confianca};'
            ),
            "pilotos": self.client.query(
                f"match {analysis} let $p, $v in pilotos-observados($a); "
                'fetch {"piloto": $p.nome, "moto": $v.modelo};'
            ),
            "pilotos_sem_capacete": self.client.query(
                f"match {analysis} let $p, $v in pilotos-sem-capacete-observados($a); "
                'fetch {"piloto": $p.nome, "moto": $v.modelo};'
            ),
            "passagens_por_sinal": self.client.query(
                f"match {analysis} registro-visual (origem: $a, objeto: $v); "
                "passagem-por-sinal (veiculo-passante: $v, sinal-cruzado: $s), "
                "has quadro $q, has tempo-s $t; $s isa! $tipo; sort $q; "
                'fetch {"veiculo": $v.modelo, "sinal": label($tipo), '
                '"quadro": $q, "tempo_s": $t};'
            ),
        }


def describe_findings(findings: dict[str, list[Document]]) -> list[str]:
    counts: dict[str, int] = {}
    for item in findings["objetos"]:
        counts[item["tipo"]] = counts.get(item["tipo"], 0) + 1
    lines = ["Objetos: " + (", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "nenhum")]
    lines.append("Pilotos inferidos pela base:")
    lines.extend(f"  - {i['piloto']} conduz {i['moto']}" for i in findings["pilotos"])
    if not findings["pilotos"]:
        lines.append("  - nenhum")
    alerts = [
        f"  - Piloto sem capacete registrado: {i['piloto']} ({i['moto']}). O modelo visual "
        "atual não detecta capacete; confirme na imagem."
        for i in findings["pilotos_sem_capacete"]
    ]
    alerts.extend(
        f"  - {i['veiculo']} cruzou a linha visual de {i['sinal']} no quadro {i['quadro']} "
        f"({i['tempo_s']:.2f} s)."
        for i in findings["passagens_por_sinal"]
    )
    lines.append("Alertas:")
    lines.extend(alerts or ["  - nenhum"])
    return lines


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--url", default="http://127.0.0.1:18000")
    common.add_argument("--database", default=DEFAULT_DATABASE)
    common.add_argument("--resultado", type=Path, help="Salva os fatos inferidos em JSON.")
    parser = argparse.ArgumentParser(
        description="Registra análises visuais na base de conhecimento e mostra as inferências."
    )
    actions = parser.add_subparsers(dest="acao", required=True)
    register = actions.add_parser(
        "registrar", parents=[common], help="Registra um relatório JSON gerado pela visão."
    )
    register.add_argument("relatorio", type=Path)
    analyze = actions.add_parser(
        "analisar", parents=[common], help="Analisa uma imagem ou vídeo e registra o resultado."
    )
    analyze.add_argument("tipo", choices=("imagem", "video"))
    analyze.add_argument("entrada", type=Path)
    analyze.add_argument("--saida", type=Path, help="Caminho do arquivo anotado.")
    analyze.add_argument("--modelo", default=visao.DEFAULT_MODEL)
    analyze.add_argument("--confianca", type=float, default=0.25)
    analyze.add_argument("--tamanho", type=int, default=640)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.acao == "analisar":
        vision_args = [args.tipo, str(args.entrada), "--modelo", args.modelo]
        vision_args += ["--confianca", str(args.confianca), "--tamanho", str(args.tamanho)]
        if args.saida:
            vision_args += ["--saida", str(args.saida)]
        status = visao.main(vision_args)
        if status != 0:
            return status
        output = args.saida or visao.default_output(args.entrada, args.tipo)
        report_file = visao.report_path(output)
    else:
        report_file = args.relatorio
    try:
        report = json.loads(report_file.read_text(encoding="utf-8"))
        if not isinstance(report, dict):
            raise IngestionError("O relatório deve ser um objeto JSON.")
        client = TypeDBClient(
            Settings(
                url=args.url,
                database=args.database,
                username=os.environ.get("TYPEDB_USER", "admin"),
                password=os.environ.get("TYPEDB_PASSWORD", "password"),
            )
        )
        client.connect()
        KnowledgeBase(client).initialize(seed=False)
        store = ObservationStore(client)
        code, summary = store.register(report)
        findings = store.findings(code)
        if summary is None:
            print(f"Análise {code} já estava registrada no banco {args.database}.")
        else:
            print(
                f"Análise {code} registrada no banco {args.database}: "
                f"{summary['objetos']} objeto(s), {summary['conducoes']} condução(ões), "
                f"{summary['passagens_por_sinal']} passagem(ns) por sinal."
            )
            if summary["ignorados"]:
                print(f"Vínculos ignorados por tipo incompatível: {summary['ignorados']}.")
        for line in describe_findings(findings):
            print(line)
        if args.resultado:
            args.resultado.parent.mkdir(parents=True, exist_ok=True)
            result = {"analise": code, "banco": args.database, "relatorio": str(report_file)}
            result.update(findings)
            args.resultado.write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            print(f"Resultado salvo em {args.resultado}.")
    except (TypeDBError, IngestionError, OSError, ValueError) as error:
        print(f"Erro: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Execução interrompida.", file=sys.stderr)
        return 130
    return 0
