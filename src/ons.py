"""Leitura, limpeza e agregação dos dados de fator de capacidade do ONS.

Fluxo: arquivos mensais (usina-hora, todo o SIN) -> eólicas do Nordeste ->
limpeza -> série horária do NE, tabela usina-dia e série diária do NE.
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd

from . import config as C

COLS_VALORES = ["val_geracaoverificada", "val_capacidadeinstalada", "val_fatorcapacidade"]


# --------------------------------------------------------------------------
# Download (opcional: reproduz a obtenção dos arquivos originais)
# --------------------------------------------------------------------------
def meses_do_periodo(inicio: str = C.INICIO, fim: str = C.FIM) -> list[pd.Timestamp]:
    return list(pd.date_range(pd.Timestamp(inicio).replace(day=1), fim, freq="MS"))


def arquivo_mes(mes: pd.Timestamp):
    return C.DIR_ONS / f"FATOR_CAPACIDADE-2_{mes.year}_{mes.month:02d}.parquet"


def baixar_ons(sobrescrever: bool = False) -> list:
    """Baixa do portal do ONS os arquivos mensais que ainda não existem."""
    import requests

    C.DIR_ONS.mkdir(parents=True, exist_ok=True)
    baixados = []
    for mes in meses_do_periodo():
        destino = arquivo_mes(mes)
        if destino.exists() and not sobrescrever:
            continue
        url = C.URL_ONS.format(ano=mes.year, mes=mes.month)
        for tentativa in range(1, 4):
            try:
                r = requests.get(url, timeout=180)
                r.raise_for_status()
                if r.content[:4] != b"PAR1":
                    raise ValueError("resposta não é um arquivo Parquet")
                destino.write_bytes(r.content)
                baixados.append(destino.name)
                print(f"baixado {destino.name} ({len(r.content) / 1e6:.1f} MB)")
                break
            except Exception as erro:  # noqa: BLE001
                print(f"falha em {url} (tentativa {tentativa}): {erro}")
                time.sleep(5 * tentativa)
        else:
            raise RuntimeError(f"não foi possível baixar {url}")
    return baixados


# --------------------------------------------------------------------------
# Leitura
# --------------------------------------------------------------------------
def _para_numero(serie: pd.Series) -> pd.Series:
    """Converte texto para float. Nos arquivos do ONS os valores vêm como texto
    em parte dos meses (e '' para ausente); em outros já vêm como double."""
    texto = serie.astype("string").str.strip().str.replace(",", ".", regex=False)
    texto = texto.mask(texto == "")
    return pd.to_numeric(texto, errors="coerce").astype("float64")


def ler_ons() -> tuple[pd.DataFrame, dict]:
    """Lê os arquivos mensais e devolve os registros usina-hora das eólicas do NE."""
    arquivos = [arquivo_mes(m) for m in meses_do_periodo()]
    faltando = [a.name for a in arquivos if not a.exists()]
    if faltando:
        raise FileNotFoundError(
            f"{len(faltando)} arquivo(s) do ONS ausente(s), ex.: {faltando[:3]}. "
            "Rode `python -m src.build_dataset --baixar-ons`."
        )

    partes, qa = [], {"arquivos": len(arquivos), "linhas_lidas": 0, "texto_nao_numerico": 0}
    for arq in arquivos:
        df = pd.read_parquet(arq, columns=C.COLUNAS_ONS)
        qa["linhas_lidas"] += len(df)
        df = df[(df["id_subsistema"] == C.SUBSISTEMA) & (df["nom_tipousina"] == C.TIPO_USINA)].copy()
        for col in COLS_VALORES:
            bruto = df[col].astype("string").str.strip()
            df[col] = _para_numero(df[col])
            # conta textos preenchidos que não viraram número (vazio não conta)
            qa["texto_nao_numerico"] += int((df[col].isna() & bruto.notna() & (bruto != "")).sum())
        df["din_instante"] = pd.to_datetime(df["din_instante"])
        df["arquivo"] = arq.name
        partes.append(df)

    df = pd.concat(partes, ignore_index=True)
    for col in ["id_subsistema", "id_estado", "nom_tipousina", "nom_modalidadeoperacao",
                "id_ons", "nom_usina_conjunto", "arquivo"]:
        df[col] = df[col].astype("string").astype("category")
    qa["linhas_eolicas_ne"] = len(df)
    qa["usinas_conjuntos"] = int(df["id_ons"].nunique())
    return df, qa


# --------------------------------------------------------------------------
# Limpeza
# --------------------------------------------------------------------------
def limpar(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Remove duplicados, padroniza o instante e marca registros válidos.

    Regras (ver README, seção de decisões):
    - chave = (id_ons, din_instante); em duplicata fica o registro do arquivo
      mais recente, pois o ONS revisa dados já publicados;
    - instantes fora da hora cheia são arredondados para a hora;
    - registro válido: geração e capacidade presentes, capacidade > 0,
      geração >= 0 e geração <= FC_MAX_VALIDO x capacidade.
      Registros inválidos saem do numerador E do denominador do FC agregado.
    """
    qa = {}
    fora_da_hora = int((df["din_instante"] != df["din_instante"].dt.floor("h")).sum())
    df["din_instante"] = df["din_instante"].dt.floor("h")
    qa["instantes_arredondados"] = fora_da_hora

    inicio, fim = pd.Timestamp(C.INICIO), pd.Timestamp(C.FIM) + pd.Timedelta(hours=23)
    fora = ~df["din_instante"].between(inicio, fim)
    qa["fora_do_periodo"] = int(fora.sum())
    df = df[~fora]

    n = len(df)
    df = (df.sort_values(["id_ons", "din_instante", "arquivo"])
            .drop_duplicates(["id_ons", "din_instante"], keep="last"))
    qa["duplicados_removidos"] = n - len(df)

    ger, cap = df["val_geracaoverificada"], df["val_capacidadeinstalada"]
    motivos = {
        "geracao_ausente": ger.isna(),
        "capacidade_ausente_ou_zero": cap.isna() | (cap <= 0),
        "geracao_negativa": ger < 0,
        "geracao_acima_de_110pct_da_capacidade": ger > C.FC_MAX_VALIDO * cap,
    }
    invalido = pd.Series(False, index=df.index)
    for nome, mascara in motivos.items():
        qa[f"invalidos_{nome}"] = int(mascara.sum())
        invalido |= mascara
    df["valido"] = ~invalido
    qa["registros_invalidos"] = int(invalido.sum())
    qa["registros_validos"] = int(df["valido"].sum())

    # O val_fatorcapacidade do ONS vem 0.0 quando a capacidade falta; por isso
    # o FC é sempre recalculado a partir de geração e capacidade.
    calc = ger / cap
    ok = df["valido"]
    qa["fc_ons_difere_do_calculado"] = int((np.abs(calc[ok] - df.loc[ok, "val_fatorcapacidade"]) > 1e-3).sum())
    return df.reset_index(drop=True), qa


# --------------------------------------------------------------------------
# Agregações
# --------------------------------------------------------------------------
def tabela_usinas(df: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por usina/conjunto: coordenadas, estado e capacidade típica."""
    v = df[df["valido"]]
    usinas = v.groupby("id_ons", observed=True).agg(
        nom_usina_conjunto=("nom_usina_conjunto", "first"),
        id_estado=("id_estado", "first"),
        modalidade=("nom_modalidadeoperacao", "first"),
        lat=("val_latitudesecoletora", "median"),
        lon=("val_longitudesecoletora", "median"),
        lat_conexao=("val_latitudepontoconexao", "median"),
        lon_conexao=("val_longitudepontoconexao", "median"),
        capacidade_mw=("val_capacidadeinstalada", "median"),
        inicio=("din_instante", "min"),
        fim=("din_instante", "max"),
    )
    # Sem coordenada da usina, usa a do ponto de conexão à rede.
    usinas["coord_origem"] = np.where(usinas["lat"].notna(), "usina", "ponto_conexao")
    usinas["lat"] = usinas["lat"].fillna(usinas["lat_conexao"])
    usinas["lon"] = usinas["lon"].fillna(usinas["lon_conexao"])
    for col in ["nom_usina_conjunto", "id_estado", "modalidade"]:
        usinas[col] = usinas[col].astype("string")
    return usinas.drop(columns=["lat_conexao", "lon_conexao"]).reset_index()


def serie_horaria(df: pd.DataFrame) -> pd.DataFrame:
    """FC horário do NE = soma da geração válida / soma da capacidade válida."""
    v = df[df["valido"]]
    h = v.groupby("din_instante").agg(
        geracao_mwmed=("val_geracaoverificada", "sum"),
        capacidade_valida_mw=("val_capacidadeinstalada", "sum"),
        n_usinas_validas=("id_ons", "nunique"),
    )
    cap_total = (df[df["val_capacidadeinstalada"] > 0]
                 .groupby("din_instante")["val_capacidadeinstalada"].sum())
    grade = pd.date_range(C.INICIO, pd.Timestamp(C.FIM) + pd.Timedelta(hours=23), freq="h", name="din_instante")
    h = h.reindex(grade)
    h["capacidade_total_mw"] = cap_total.reindex(grade)
    h["fc"] = h["geracao_mwmed"] / h["capacidade_valida_mw"]
    h["cobertura"] = h["capacidade_valida_mw"] / h["capacidade_total_mw"]
    return h.reset_index()


def usina_dia(df: pd.DataFrame) -> pd.DataFrame:
    """Tabela tidy usina-dia (capacidade média e geração média dos registros válidos)."""
    v = df[df["valido"]].assign(data=lambda x: x["din_instante"].dt.normalize())
    return (v.groupby(["id_ons", "data"], observed=True)
              .agg(capacidade_mw=("val_capacidadeinstalada", "mean"),
                   geracao_mwmed=("val_geracaoverificada", "mean"),
                   horas_validas=("din_instante", "size"))
              .reset_index())


def serie_diaria(h: pd.DataFrame) -> pd.DataFrame:
    """Agrega a série horária em dias (horário de Brasília).

    FC diário = soma das gerações horárias / soma das capacidades horárias,
    ou seja, a energia gerada no dia dividida pela energia máxima possível.
    """
    h = h.assign(data=h["din_instante"].dt.normalize())
    d = h.groupby("data").agg(
        geracao_mwmed=("geracao_mwmed", "mean"),
        capacidade_mw=("capacidade_valida_mw", "mean"),
        soma_ger=("geracao_mwmed", "sum"),
        soma_cap=("capacidade_valida_mw", "sum"),
        soma_cap_total=("capacidade_total_mw", "sum"),
        horas_com_dado=("fc", "count"),
        n_usinas=("n_usinas_validas", "max"),
    )
    d["fc"] = d["soma_ger"] / d["soma_cap"]
    d["cobertura"] = d["soma_cap"] / d["soma_cap_total"]
    d["qualidade_ok"] = (d["horas_com_dado"] == 24) & (d["cobertura"] >= C.COBERTURA_MIN)
    return d.drop(columns=["soma_ger", "soma_cap", "soma_cap_total"]).reset_index()
