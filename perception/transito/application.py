import re
from pathlib import Path
from urllib.parse import quote

from transito.client import Document, TypeDBClient, TypeDBError

PROJECT_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_BASE_ROOT = PROJECT_ROOT / "knowledge_base"
REQUIRED_FUNCTIONS = (
    "pilotos",
    "motoristas",
    "equipamentos-do-veiculo",
    "pilotos-sem-capacete-cadastrado",
)
OBSERVATION_FUNCTIONS = ("pilotos-observados", "pilotos-sem-capacete-observados")


def defines_functions(schema: str, names: tuple[str, ...]) -> bool:
    return all(re.search(r"\bfun\s+" + re.escape(name) + r"\s*\(", schema) for name in names)


class KnowledgeBase:
    def __init__(self, client: TypeDBClient, root: Path = KNOWLEDGE_BASE_ROOT) -> None:
        self.client = client
        self.root = root

    def initialize(self, seed: bool = True) -> bool:
        response = self.client.request("GET", "/v1/databases")
        if not isinstance(response, dict) or not isinstance(response.get("databases"), list):
            raise TypeDBError("O TypeDB retornou uma lista de bancos inválida.")
        database = self.client.settings.database
        path = f"/v1/databases/{quote(database, safe='')}"
        if database not in {item["name"] for item in response["databases"]}:
            self.client.request("POST", path)
        schema = self.client.request("GET", f"{path}/schema", as_text=True)
        if schema in ("", "define", "define;"):
            self.client.query(self.read(self.root / "schema.tql"), "schema")
            schema = ""
        elif not defines_functions(schema, REQUIRED_FUNCTIONS):
            raise TypeDBError(
                "O banco já possui outro esquema. Escolha um banco novo com --database."
            )
        # Bancos criados antes da camada de observação recebem apenas a extensão.
        if not defines_functions(schema, OBSERVATION_FUNCTIONS):
            self.client.query(self.read(self.root / "observacoes.tql"), "schema")
        if not seed:
            return False
        if self.client.query('match $v isa veiculo; limit 1; fetch {"codigo": $v.codigo};'):
            return False
        self.client.query(self.read(self.root / "dados.tql"), "write")
        return True

    def examples(self) -> dict[str, list[Document]]:
        paths = sorted((self.root / "consultas").glob("*.tql"))
        if not paths:
            raise ValueError("Nenhuma consulta foi encontrada na pasta consultas.")
        return {path.stem: self.client.query(self.read(path)) for path in paths}

    @staticmethod
    def read(path: Path) -> str:
        if path.suffix != ".tql":
            raise ValueError("O arquivo de consulta deve ter a extensão .tql.")
        query = path.read_text(encoding="utf-8").strip()
        if not query:
            raise ValueError(f"O arquivo {path.name} está vazio.")
        return query
