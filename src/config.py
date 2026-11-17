"""Configurações do pipeline: caminhos, período e parâmetros de tratamento.

Todas as decisões numéricas ficam aqui para que possam ser citadas no relatório
e alteradas em um só lugar.
"""
from pathlib import Path

# --- Caminhos --------------------------------------------------------------
RAIZ = Path(__file__).resolve().parents[1]
DATA = RAIZ / "data"
DIR_ONS = DATA / "ons_fator_capacidade_2022-01_a_2026-10"   # arquivos originais do ONS
DIR_CLIMA_RAW = DATA / "raw" / "openmeteo"                  # respostas brutas da API (cache)
DIR_INTERIM = DATA / "interim"                              # tabelas intermediárias
DIR_PROCESSED = DATA / "processed"                          # base final
DIR_REPORTS = RAIZ / "reports"

BASE_FINAL = DIR_PROCESSED / "base_fc_eolico_ne_diario.parquet"
RELATORIO_QUALIDADE = DIR_REPORTS / "qualidade_dados.json"

# --- Recorte ---------------------------------------------------------------
INICIO = "2022-01-01"
FIM = "2026-10-31"
SUBSISTEMA = "NE"          # id_subsistema no ONS
TIPO_USINA = "Eólica"      # nom_tipousina no ONS

# --- Fonte ONS -------------------------------------------------------------
URL_ONS = (
    "https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/fator_capacidade_2_di/"
    "FATOR_CAPACIDADE-2_{ano}_{mes:02d}.parquet"
)
COLUNAS_ONS = [
    "id_subsistema", "id_estado", "nom_tipousina", "nom_modalidadeoperacao",
    "id_ons", "nom_usina_conjunto",
    "val_latitudesecoletora", "val_longitudesecoletora",
    "val_latitudepontoconexao", "val_longitudepontoconexao",
    "din_instante",
    "val_geracaoverificada", "val_capacidadeinstalada", "val_fatorcapacidade",
]

# Registro usina-hora é considerado suspeito (e excluído do numerador e do
# denominador) quando a geração passa de 110% da capacidade instalada.
# Entre 100% e 110% a diferença é atribuída a atrasos no cadastro de capacidade.
FC_MAX_VALIDO = 1.10

# Dias com menos de 95% da capacidade com dado válido recebem flag de qualidade.
COBERTURA_MIN = 0.95

# --- Clima (Open-Meteo, reanálise ERA5) -----------------------------------
URL_OPENMETEO = "https://archive-api.open-meteo.com/v1/archive"
MODELO_CLIMA = "era5"
VARIAVEL_VENTO = "wind_speed_100m"
N_PONTOS_CLIMA = 20        # pontos representativos do parque eólico do NE (k-means)
SEMENTE = 42

# Os registros do ONS estão em horário de Brasília (UTC-3, sem horário de verão
# desde 2019). A API é consultada em UTC e convertida para esse fuso.
FUSO_ONS = "America/Sao_Paulo"
