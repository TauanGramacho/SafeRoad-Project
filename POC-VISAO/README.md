# Prova de conceito: avaliação do YOLO11n em cenas de trânsito

Mede o desempenho do modelo YOLO11n, pré-treinado no COCO, na identificação de
entidades do domínio de trânsito a partir de quadros de vídeo veicular. Não
produz vídeos anotados nem descrições: o objetivo é obter métricas comparáveis
com a literatura, e não demonstrar o funcionamento do modelo.

## Instalação

```bash
conda create -n SafeRoad python=3.12 -y
conda activate SafeRoad
pip install -r requirements.txt
```

Use Python 3.11 ou 3.12. Em versões mais recentes pode não haver pacote
pré-compilado do NumPy para Windows, caso em que o pip tenta compilá-lo e falha
por ausência de compilador C.

Os pesos `yolo11n.pt` são baixados automaticamente na primeira execução, o que
exige acesso à internet. A avaliação roda em CPU.

## Qual conjunto de dados usar

### Opção recomendada: BDD100K

É o conjunto mais adequado ao SafeRoad, por ser de câmera frontal monocular
embarcada, a mesma configuração do sistema proposto, e por trazer os atributos
de clima e período do dia que permitem segmentar os resultados.

1. Registre-se em <https://bdd-data.berkeley.edu/> e aceite os termos de uso
   acadêmico.
2. Baixe dois arquivos:
   - `100k Images` (as imagens; a divisão `val` tem 10 mil imagens)
   - `Detection 2020 Labels` (as anotações em JSON)
3. Descompacte de modo que fique assim:

```
dados/bdd100k/
├── images/100k/val/        (as imagens .jpg)
└── labels/det_val.json     (as anotações)
```

Execute:

```bash
python executar.py \
  --imagens dados/bdd100k/images/100k/val \
  --rotulos dados/bdd100k/labels/det_val.json \
  --limite 500
```

Comece com `--limite 500` para conferir se está tudo certo, o que leva poucos
minutos em CPU. Depois remova o limite para avaliar as 10 mil imagens.

### Redistribuições no formato Supervisely

Algumas redistribuições do BDD100K, como a do Dataset Ninja, usam o formato
Supervisely: cada divisão contém as subpastas `ann`, com um JSON por imagem, e
`img`. Basta apontar para a pasta da divisão:

```bash
python executar.py --imagens data/train --limite 2000
```

O formato é detectado automaticamente, e as geometrias de polígono, retângulo e
máscara são convertidas em caixas envolventes.

Atenção: o subconjunto de dez mil imagens foi anotado para segmentação e não
contém as classes de semáforo e sinalização, de modo que apenas seis das oito
classes de interesse podem ser avaliadas com ele.

### Opção rápida: qualquer conjunto no formato YOLO

Serve para um primeiro ensaio enquanto o cadastro no BDD100K não sai. Conjuntos
de trânsito no formato YOLO estão disponíveis no Roboflow Universe e no Kaggle.
A estrutura esperada é a usual:

```
dados/meu_conjunto/
├── data.yaml
└── valid/
    ├── images/
    └── labels/
```

```bash
python executar.py \
  --imagens dados/meu_conjunto/valid/images \
  --classes dados/meu_conjunto/data.yaml
```

Atenção: conjuntos de terceiros costumam usar nomes de classe próprios. Se os
nomes não constarem de `mapeamento.py`, as anotações correspondentes são
excluídas e o programa informa quais foram. Acrescente as correspondências
necessárias naquele arquivo.

## Organização

| Arquivo | Responsabilidade |
|---|---|
| `config.py` | Parâmetros da execução: limiares, resolução, caminhos |
| `mapeamento.py` | Correspondência entre as classes do conjunto e as do COCO |
| `dataset.py` | Leitura das anotações nos formatos BDD100K e YOLO |
| `modelo.py` | Carregamento do YOLO e execução da inferência |
| `avaliacao.py` | IoU, pareamento, precisão, revocação, F1, AP e mAP |
| `relatorio.py` | Tabelas, JSON e CSV de saída |
| `executar.py` | Orquestra as quatro etapas |
| `testes/` | Testes das métricas e do fluxo, sem necessidade do modelo |

## O que é produzido

No terminal, a tabela de métricas por classe, o mAP e o desempenho segmentado
por período do dia e condição climática. Em `resultados/`:

- `relatorio.json` com todos os números e os parâmetros da execução
- `metricas-por-classe.csv` para uso direto no texto do trabalho

## Métricas adotadas

Uma detecção é considerada correta quando sobrepõe uma anotação da mesma classe
com IoU igual ou superior ao limiar, que por padrão é 0,5. O pareamento é feito
em ordem decrescente de confiança, e cada anotação pode ser reivindicada uma
única vez, de modo que detecções repetidas sobre o mesmo objeto contam como
falsos positivos.

- **Precisão**: proporção das detecções que estavam corretas.
- **Revocação**: proporção dos objetos anotados que foram encontrados.
- **F1**: média harmônica entre as duas.
- **AP**: área sob a curva de precisão e revocação, por interpolação em todos os
  pontos, conforme a convenção adotada desde o PASCAL VOC 2010.
- **mAP@0,5**: média da AP entre as classes presentes no conjunto.
- **mAP@0,5:0,95**: média do mAP sobre dez limiares de IoU, de 0,50 a 0,95,
  conforme a convenção do COCO.

Precisão, revocação e F1 são calculadas no ponto de operação, isto é,
considerando apenas as detecções acima do limiar de confiança (0,25 por padrão).
A AP considera toda a curva, e por isso a inferência roda com limiar próximo de
zero.

## Classes sem equivalente

O YOLO11n detecta as classes do COCO, que não coincidem com as dos conjuntos
anotados para trânsito. O `mapeamento.py` registra as correspondências adotadas
e as exclusões, que são informadas em toda execução e gravadas no relatório. As
duas exclusões relevantes no BDD100K são `traffic sign`, cuja categoria abrange
toda a sinalização vertical enquanto o COCO contempla apenas a placa de parada
obrigatória norte-americana, e `train`, sem equivalente no subconjunto adotado.

Esse desalinhamento é resultado da avaliação, e não defeito dela: ele delimita
quais entidades do domínio são efetivamente observáveis com um modelo
pré-treinado genérico.

## Testes

```bash
python testes/test_avaliacao.py   # métricas, com casos de resultado conhecido
python testes/test_fluxo.py       # fluxo completo, com modelo simulado
```

Ambos rodam sem o Ultralytics e sem conjunto de dados.
