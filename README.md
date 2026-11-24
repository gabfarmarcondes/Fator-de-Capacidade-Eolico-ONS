# Fator-de-Capacidade-Eolico-ONS
Trabalho de Ciência de Dados sobre o Fator de Capacidade Eólico (ONS) do subsistema do Nordeste que tem o objetivo de prever o fator capacidade do dia seguinte e investigar o que explica sua variação.

## Definição do Problema

### Perguntas e Hipóteses
* **Pergunta 1:** Quanto da variação diária do FC eólico do Nordeste é explicado pela sazonalidade e pelo vento, e o  calendário (fins de semana e feriados) tem algum efeito?
* **Pergunta 2:** É possível prever o FC médio do dia seguinte com erro menor que o de um modelo de persistência?
* **Hipótese 1:** O FC é maior na safra dos ventos (jul–out) do que no 1º semestre. Será testada com o teste de  Mann-Whitney entre os dois períodos, ano a ano.
* **Hipótese 2:** A velocidade do vento a 100 m explica a maior parte da variação diária do FC. Será testada pela  correlação e pelo R² de uma regressão do FC sobre o vento.
* **Hipótese 3:** Em domingos e feriados, o FC fica abaixo do esperado para o vento observado. Será testada comparando os resíduos do modelo da H2 entre  dias úteis e não úteis.

### Recorte dos Dados
* **Variável-alvo:** FC diário das usinas eólicas do Nordeste: soma da geração de todas as usinas dividida pela soma das capacidades. Assim, usinas maiores pesam mais no resultado.
* **Subsistema:** Nordeste, que concentra a maior parte da capacidade eólica do país.
* **Período:** janeiro de 2022 até outubro de 2026.
* **Formato dos dados:** os dados estão em `.parquet`.

### Granularidade e Horizonte:
A análise será diária, com previsão para o dia seguinte (D+1).
* **Diária:** juntar as horas de cada dia, tira a diferença entre dia e noite e mantém o que muda de um dia para o outro.
* **D+1:** é  o prazo em que o ONS planeja a operação do dia seguinte Nesse prazo, repetir o valor de ontem já acerta bastante, então superá-lo é um bom teste para o modelo.

### Integração com clima e feriados
O vento virá da API Open-Meteo Historical, que fornece a velocidade do vento a 100 m, hora a hora. Ele serve para mostrar quanto o vento explica o FC (H2) e para calcular o FC esperado em cada dia (H3). Na previsão, é a variável do cenário (b).

Os feriados nacionais virão da biblioteca Python holidays. Ela serve para marcar fins de semana e feriados e testar se o FC cai nesses dias por corte de geração (H3). Na previsão, entra como variável nos dois cenários. As duas fontes são associadas aos dados do ONS pela data.

### Modelagem e Avaliação
* **Baselines:** persistência (FC de ontem) e média histórica do mês.
* **Modelos:** regressão Ridge e gradient boosting (scikit-learn), com defasagens do FC, médias móveis, mês, dia da semana, feriado e, no cenário (b), o vento.
* **Validação:** treino até dezembro de 2025 e teste em 2026, que inclui uma safra completa. A escolha de hiperparâmetros usará TimeSeriesSplit sem embaralhar os dias.
* **Métricas:** MAE e RMSE em pontos percentuais de FC, além do ganho relativo sobre a persistência.

## Preparação e Integração dos Dados

A preparação gera uma base diária *tidy* (uma linha por dia, uma variável por coluna) em
`data/processed/base_fc_eolico_ne_diario.parquet`, a partir dos arquivos originais do ONS,
do vento da API Open-Meteo e dos feriados da biblioteca `holidays`.

### Como reproduzir

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python -m src.build_dataset              # usa os Parquet do ONS em data/ons_fator_capacidade_2022-01_a_2026-10/
python -m src.build_dataset --baixar-ons # baixa antes, do portal do ONS, os meses que faltarem
```

Na primeira execução o vento é baixado da API (20 requisições, alguns minutos) e guardado em
`data/raw/openmeteo/`; nas seguintes, o cache é reaproveitado. O notebook
`notebooks/02_preparacao_dados.ipynb` confere a base e mostra as evidências de cada decisão.

| Arquivo | Conteúdo |
| --- | --- |
| `src/config.py` | caminhos, período e todos os parâmetros de tratamento |
| `src/ons.py` | leitura, limpeza e agregação dos dados do ONS |
| `src/clima.py` | pontos de clima, download do vento e índice diário |
| `src/feriados.py` | calendário (fins de semana, feriados, carnaval) |
| `src/build_dataset.py` | executa tudo, valida e salva as saídas |
| `reports/qualidade_dados.json` | contagens de cada tratamento |

### Decisões de tratamento (dados do ONS)

- **Recorte:** dos 8,8 milhões de registros usina-hora dos 58 arquivos, ficam os 5,9 milhões de usinas eólicas do subsistema Nordeste (190 usinas/conjuntos).
- **Tipos:** em parte dos meses, geração, capacidade e FC vêm como texto (com `''` para ausente); em outros, como número. Tudo é convertido para `float`.
- **Datas:** `din_instante` já vem como data-hora, sempre na hora cheia. É tratado como horário de Brasília (fuso confirmado no notebook, seção 5).
- **Duplicados:** a chave é `(id_ons, din_instante)`. Não há duplicados no período; se houver em uma nova versão dos arquivos, fica o registro do arquivo mais recente, porque o ONS revisa dados já publicados.
- **Ausentes e suspeitos:** 4.523 registros usina-hora (0,08%) foram marcados como inválidos: geração ausente (552), capacidade ausente (3.840), geração negativa (6) ou geração acima de 110% da capacidade (677, com FC de até 12). Eles saem do numerador **e** do denominador do FC, para não distorcer o valor agregado. Entre 100% e 110%, a diferença é atribuída a atrasos no cadastro da capacidade e o registro é mantido.
- **FC recalculado:** o `val_fatorcapacidade` do ONS vem 0 quando falta a capacidade, então o FC é sempre recalculado como geração ÷ capacidade.
- **Agregação temporal:** FC horário do NE = Σ geração ÷ Σ capacidade das usinas válidas naquela hora. FC diário = soma das gerações horárias ÷ soma das capacidades horárias (energia gerada ÷ energia máxima possível no dia).
- **Qualidade diária:** todos os 1.765 dias têm 24 horas com dado e pelo menos 99% da capacidade com registro válido, então nenhum dia foi descartado. A coluna `qualidade_ok` marca dias com menos de 95%, para uso futuro.
- **Valores baixos:** os dias de menor FC (0,03 a 0,06, em fev–abr/2024) têm vento médio abaixo de 3 m/s. São reais e ficam na base.

### Integração com o clima (Open-Meteo)

- **Fonte:** vento a 100 m (altura típica dos rotores) da reanálise ERA5, via API Open-Meteo Historical, com dados horários.
- **Escala geográfica:** as usinas foram agrupadas em 20 pontos por k-means, ponderado pela capacidade instalada. Com 20 pontos, 93% da capacidade fica a menos de 50 km do seu ponto, distância próxima da resolução do ERA5 (~28 km). Com 10 pontos, seriam só 67%. A lista dos pontos e a associação usina → ponto ficam em `data/interim/`.
- **Escala temporal:** a API é consultada em UTC e convertida para horário de Brasília antes de agregar por dia. O FC horário tem a maior correlação com o vento deslocado em −1 h e não em +3 h, o que confirma o fuso. A diferença de 1 h vem de o ONS publicar a média da hora e o ERA5 o valor instantâneo.
- **Agregação:** para cada ponto calculam-se a média diária do vento e do vento ao cubo (a potência do vento cresce com v³). O índice do NE é a média dos pontos ponderada pela capacidade que cada ponto representa **naquele dia**, então acompanha a entrada de novas usinas.

### Integração com feriados (`holidays`)

- Os feriados nacionais (categoria pública da biblioteca) são associados pela data. Inclui o Dia da Consciência Negra a partir de 2024, quando virou feriado nacional.
- O carnaval é ponto facultativo, mas derruba a carga do sistema, então entra em coluna própria (categoria opcional da biblioteca).
- Feriados estaduais e municipais não entram: o corte de geração eólica depende da carga do sistema interligado, dominada pelos feriados nacionais.
- `dia_nao_util` = fim de semana, feriado nacional ou carnaval.

### Indicadores econômicos

Não foram incluídos. O alvo é a fração da capacidade eólica efetivamente gerada em cada dia, que depende do vento e, no caso do corte de geração, da carga diária. Indicadores do IBGE, IPEADATA e Banco Central são mensais ou trimestrais e não explicam a variação de um dia para o outro.

### Dicionário da base final

| Coluna | Descrição |
| --- | --- |
| `data` | dia (horário de Brasília) |
| `ano`, `mes`, `dia_semana` | componentes da data (`dia_semana`: 0 = segunda, 6 = domingo) |
| `fc` | **alvo**: FC eólico diário do NE (0 a 1) |
| `geracao_mwmed` | geração média do dia (MWmed) |
| `capacidade_mw` | capacidade instalada média do dia (MW) |
| `n_usinas` | usinas/conjuntos com dado válido |
| `horas_com_dado`, `cobertura` | horas com dado e fração da capacidade com registro válido |
| `qualidade_ok` | 24 horas com dado e cobertura ≥ 95% |
| `vento_100m_ms` | vento médio a 100 m, ponderado pela capacidade (m/s) |
| `vento_100m_cubo` | média de v³, ponderada pela capacidade (m³/s³) |
| `vento_100m_desvio_entre_pontos` | dispersão do vento entre os pontos (m/s) |
| `pontos_clima` | pontos com usinas em operação no dia |
| `fim_de_semana`, `feriado_nacional`, `nome_feriado`, `carnaval`, `dia_nao_util` | calendário |
| `safra_ventos` | julho a outubro (H1) |

## Investigação dos Dados e Consultas SQL

O notebook `notebooks/03_investigacao_sql.ipynb` faz a análise exploratória com 7 consultas SQL (DuckDB, direto nos
arquivos Parquet) e testa as hipóteses H1–H3. Ele usa as saídas da etapa 2, então rode antes
`python -m src.build_dataset` se ainda não tiver a base.

| Consulta | Pergunta | Recursos de SQL |
| --- | --- | --- |
| 1 | Em que meses o FC é maior? | agregação por ano e mês, CTE |
| 2 | O FC está mudando com o tempo? | janelas `lag(…, 12)` e média móvel de 12 meses |
| 3 | O mesmo vento gera o mesmo FC todo ano? | CTE por faixa de vento, `pivot` |
| 4 | Em que horas o FC cai, e isso mudou? | CTE com FC esperado de 2022, resíduo por hora e ano |
| 5 | O FC muda com o dia da semana? | CTE com FC esperado pelo vento |
| 6 | Quais dias ficaram muito fora do esperado? | janela de ±15 dias (z-score) |
| 7 | O Sul se comporta como o Nordeste? | leitura dos arquivos brutos do ONS, `lag` por região |

**Principais resultados:**

- **H1 confirmada:** na safra (jul–out) o FC é cerca de 0,14 maior que em jan–jun (IC 95%: 0,11 a 0,17).
- **H2 confirmada:** só o vento explica cerca de 86% da variação do FC diário (R² de 0,86, IC 95%: 0,82 a 0,88).
- **H3 confirmada para domingos, não para feriados:** o domingo fica cerca de 0,028 abaixo dos dias úteis da mesma semana com o mesmo vento. O efeito era zero em 2022 e cresce até cerca de −0,04 em 2026. Feriados em dia útil não mostram diferença significativa.
- **Para o mesmo vento, o FC cai a cada ano,** sobretudo em dias de vento forte e entre 9h e 15h, quando a geração solar é maior. O padrão é compatível com o aumento dos cortes de geração (*curtailment*) no Nordeste a partir de agosto de 2023.
- **O Sul é bem menos previsível que o Nordeste:** a correlação do FC com o dia anterior é de 0,48, contra 0,83 no NE.

Como os dias vizinhos são parecidos (autocorrelação), os testes usam médias mensais, comparações dentro da mesma semana e bootstrap em blocos de 14 dias, em vez de tratar cada dia como independente.
