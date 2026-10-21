# SafeRoad 

Protótipo de visão computacional para trânsito integrado a uma base de conhecimento em TypeDB. A visão detecta objetos em imagens e vídeos; a base recebe essas observações como fatos e aplica regras sobre elas (por exemplo, "piloto sem capacete registrado").

## Estrutura

```text
perception/
  visao.py          # atividade 1: análise de imagem ou vídeo
  prototipo.py      # atividade 2: CLI da base de conhecimento
  roadguard.py      # integração: analisa, registra na base e mostra os alertas
  transito/         # código dos três comandos
knowledge_base/
  compose.yaml      # TypeDB em Docker
  schema.tql        # ontologia da atividade 2
  observacoes.tql   # extensão para observações visuais
  dados.tql         # dados de exemplo da atividade 2
  consultas/        # consultas da atividade 2
tests/              # testes automatizados e relatórios de referência
docs/testes/        # plano de testes e evidências de execução
```

## Instalação

Requisitos: Python 3.10 ou superior e Docker Desktop (para a base). No PowerShell, na raiz do projeto:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-visao.txt
```

Para rodar os testes, instale também `requirements-dev.txt`.

## Atividade 1: análise de imagens e vídeos

```powershell
python perception\visao.py imagem "C:\caminho\para\imagem.jpg"
python perception\visao.py video "C:\caminho\para\video.mp4"
```

Por padrão, a imagem anotada é salva ao lado da entrada com o sufixo `_anotada`, e o vídeo é salvo como MP4 com o sufixo `_anotado`. Cada análise também gera um relatório JSON com o sufixo `_relatorio`.

É possível indicar o caminho de saída, outros pesos YOLO compatíveis com as classes COCO e ajustar a confiança ou a resolução:

```powershell
python perception\visao.py imagem "C:\caminho\para\imagem.jpg" --saida "C:\caminho\para\resultado.jpg" --confianca 0.3 --tamanho 640
```

O modelo `yolo11n.pt` é baixado automaticamente pelo Ultralytics na primeira execução, que por isso precisa de internet. CPU é suficiente para experimentar, mas vídeos podem demorar; uma GPU compatível acelera a análise. Veja a [documentação do YOLO11](https://docs.ultralytics.com/models/yolo11/) e a [documentação de rastreamento](https://docs.ultralytics.com/modes/track/).

### O que o protótipo detecta e descreve

- Objetos das classes COCO selecionadas: pessoa, bicicleta, carro, moto, ônibus, caminhão, semáforo e placa de pare.
- Em imagens: caixas delimitadoras, confiança e posição no quadro. Também estima as linhas retas da pista e, quando há ao menos três limites visíveis, informa se um veículo está na faixa esquerda, central ou direita.
- Em vídeos: usa ByteTrack para manter IDs entre quadros e resume em quantos quadros cada objeto apareceu.
- Possível passagem por sinal: registrada quando a trajetória de um veículo rastreado cruza a altura da caixa de um semáforo ou placa de pare.
- Possível condução: uma pessoa cuja caixa se sobrepõe à parte de cima de uma moto é associada a ela (em vídeo, em pelo menos 3 quadros).
- As linhas de pista são estimadas com Canny e Hough, sem um modelo treinado para faixas.

## Atividade 2: base de conhecimento TypeDB

Com o Docker em execução:

```powershell
docker compose -f knowledge_base\compose.yaml up -d
python perception\prototipo.py iniciar
python perception\prototipo.py demonstrar
python perception\prototipo.py validar
python perception\prototipo.py consultar knowledge_base\consultas\01-veiculos.tql
```

## Integração: visão + base de conhecimento

O comando `roadguard.py` leva o resultado da visão para a base. Cada objeto visto vira um fato tipado (`pessoa`, `moto`, `carro`, `caminhao`, `semaforo`, `placa-pare`; ônibus e bicicleta viram `objeto-generico`). Cada pessoa associada a uma moto vira uma relação `conducao`, e cada passagem por sinal vira uma relação `passagem-por-sinal`. As funções da atividade 2 (`pilotos`, `pilotos-sem-capacete-cadastrado`) passam a valer também para o que foi observado.

```powershell
# analisa a mídia, registra na base e mostra as inferências
python perception\roadguard.py analisar video "C:\caminho\para\video.mp4"

# registra um relatório JSON já gerado pela visão (não precisa do YOLO)
python perception\roadguard.py registrar tests\fixtures\relatorio_video.json --resultado resultado.json
```

As observações ficam no banco `roadguard` (mude com `--database`), separadas dos dados de exemplo da atividade 2 no banco `transito`. Registrar o mesmo relatório duas vezes não duplica os fatos. Bancos criados antes da integração recebem a extensão `observacoes.tql` automaticamente.

## Testes

```powershell
python -m pip install -r requirements-dev.txt
docker compose -f knowledge_base\compose.yaml up -d
$env:TYPEDB_TEST_URL = "http://127.0.0.1:18000"
python -m pytest -v
```

Sem `TYPEDB_TEST_URL`, os testes que usam o banco são pulados. O plano de testes, os casos, os defeitos encontrados e as evidências estão em [docs/testes/plano-de-testes.md](docs/testes/plano-de-testes.md).

## Limitações

- **Faixas:** a estimativa procura linhas retas na parte de baixo da imagem. Pode confundir marcações com sombras, bordas ou outros contrastes, não acompanha curvas e depende de câmera frontal com marcações visíveis. Sem limites suficientes, informa apenas a posição no quadro.
- **Pista e semáforo:** o protótipo não segmenta a pista e não lê a cor ou o estado do semáforo.
- **Passagem por sinal:** é uma regra geométrica aproximada para vídeo frontal, com o veículo se deslocando para a parte de baixo do quadro. Depende da câmera, da perspectiva, de o objeto estar visível e de o rastreador manter o mesmo ID. Não confirma que o veículo passou pelo sinal nem que houve infração.
- **Condução:** a associação pessoa–moto é geométrica e pode errar com garupa, pedestres próximos ou troca de ID.
- **Capacete:** o modelo COCO não detecta capacete. Por isso, o alerta "piloto sem capacete registrado" significa que o capacete não foi verificado, não que ele está ausente.
- **Modelo:** pode falhar com objetos distantes, parcialmente encobertos, iluminação ruim ou cenas fora dos exemplos comuns do COCO.
- **Descrições:** são regras sobre as detecções, não uma compreensão semântica completa do vídeo.
