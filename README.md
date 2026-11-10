# Fator-de-Capacidade-Eolico-ONS
Trabalho de Ciência de Dados sobre o Fator de Capacidade Eólico (ONS) do subsistema do Nordeste que tem o objetivo de prever o fator capacidade do dia seguinte e investigar o que explica sua variação.

## Perguntas e Hipóteses
* **Pergunta 1:** Quanto da variação diária do FC eólico do Nordeste é explicado pela sazonalidade e pelo vento, e o  calendário (fins de semana e feriados) tem algum efeito?

* **Pergunta 2:** É possível prever o FC médio do dia seguinte com erro menor que o de um modelo de persistência?

* **Hipótese 1:** O FC é maior na safra dos ventos (jul–out) do que no 1º semestre. Será testada com o teste de  Mann-Whitney entre os dois períodos, ano a ano.

* **Hipótese 2:** A velocidade do vento a 100 m explica a maior parte da variação diária do FC. Será testada pela  correlação e pelo R² de uma regressão do FC sobre o vento.

* **Hipótese 3:** Em domingos e feriados, o FC fica abaixo do esperado para o vento observado. Será testada comparando os resíduos do modelo da H2 entre  dias úteis e não úteis.

## Recorte dos Dados
* **Variável-alvo:** FC diário das usinas eólicas do Nordeste: soma da geração de todas as usinas dividida pela soma das capacidades. Assim, usinas maiores pesam mais no resultado.

* **Subsistema:** Nordeste, que concentra a maior parte da capacidade eólica do país.

* **Período:** janeiro de 2022 até outubro de 2026.

* **Formato dos dados:** os dados estão em `.parquet`.

## Granularidade e Horizonte:
A análise será diária, com previsão para o dia seguinte (D+1).
* **Diária:** juntar as horas de cada dia, tira a diferença entre dia e noite e mantém o que muda de um dia para o outro.
* **D+1:** é  o prazo em que o ONS planeja a operação do dia seguinte Nesse prazo, repetir o valor de ontem já acerta bastante, então superá-lo é um bom teste para o modelo.

## Integração com clima e feriados
O vento virá da API Open-Meteo Historical, que fornece a velocidade do vento a 100 m, hora a hora. Ele serve para mostrar quanto o vento explica o FC (H2) e para calcular o FC esperado em cada dia (H3). Na previsão, é a variável do cenário (b).

Os feriados nacionais virão da biblioteca Python holidays. Ela serve para marcar fins de semana e feriados e testar se o FC cai nesses dias por corte de geração (H3). Na previsão, entra como variável nos dois cenários. As duas fontes são associadas aos dados do ONS pela data.

## Modelagem e Avaliação
* **Baselines:** persistência (FC de ontem) e média histórica do mês.
* **Modelos:** regressão Ridge e gradient boosting (scikit-learn), com defasagens do FC, médias móveis, mês, dia da semana, feriado e, no cenário (b), o vento.
* **Validação:** treino até dezembro de 2025 e teste em 2026, que inclui uma safra completa. A escolha de hiperparâmetros usará TimeSeriesSplit sem embaralhar os dias.
* **Métricas:** MAE e RMSE em pontos percentuais de FC, além do ganho relativo sobre a persistência.