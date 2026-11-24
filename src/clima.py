"""Integração com o clima: vento a 100 m da reanálise ERA5 via Open-Meteo.

Escala geográfica: as ~190 usinas/conjuntos eólicos do NE são agrupadas em
N_PONTOS_CLIMA pontos por k-means ponderado pela capacidade instalada. Cada
usina usa o vento do seu ponto.

Escala temporal: a API devolve dados horários em UTC; eles são convertidos para
horário de Brasília (fuso do ONS) e agregados por dia. O índice diário do NE é
a média dos pontos ponderada pela capacidade instalada que cada ponto
representa naquele dia, então acompanha a entrada de novas usinas.
"""
from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd

from . import config as C


# --------------------------------------------------------------------------
# Pontos representativos
# --------------------------------------------------------------------------
def distancia_km(lat1, lon1, lat2, lon2):
    """Distância de grande círculo (fórmula de haversine)."""
    lat1, lon1, lat2, lon2 = (np.radians(np.asarray(x, dtype=float)) for x in (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * np.arcsin(np.sqrt(a))


def definir_pontos(usinas: pd.DataFrame, k: int = C.N_PONTOS_CLIMA) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Agrupa as usinas em k pontos (k-means ponderado pela capacidade).

    Retorna (pontos, mapa_usina_ponto)."""
    from sklearn.cluster import KMeans

    u = usinas.dropna(subset=["lat", "lon", "capacidade_mw"]).copy()
    X = u[["lat", "lon"]].to_numpy(dtype=float)
    km = KMeans(n_clusters=k, random_state=C.SEMENTE, n_init=10)
    km.fit(X, sample_weight=u["capacidade_mw"].to_numpy(dtype=float))

    # Ordena os pontos por latitude para ids estáveis e legíveis (P01 = mais ao norte)
    centros = km.cluster_centers_
    ordem = np.argsort(-centros[:, 0])
    novo_id = {antigo: f"P{i + 1:02d}" for i, antigo in enumerate(ordem)}
    u["ponto_id"] = [novo_id[r] for r in km.labels_]
    centros_df = pd.DataFrame({
        "ponto_id": [novo_id[i] for i in range(k)],
        "lat": np.round(centros[:, 0], 4),
        "lon": np.round(centros[:, 1], 4),
    })
    u = u.merge(centros_df.rename(columns={"lat": "lat_ponto", "lon": "lon_ponto"}), on="ponto_id")
    u["distancia_km"] = distancia_km(u["lat"], u["lon"], u["lat_ponto"], u["lon_ponto"]).round(1)

    pontos = (u.groupby("ponto_id")
                .agg(capacidade_mw=("capacidade_mw", "sum"),
                     n_usinas=("id_ons", "size"),
                     estados=("id_estado", lambda s: ",".join(sorted(set(s)))),
                     distancia_media_km=("distancia_km", "mean"),
                     distancia_max_km=("distancia_km", "max"))
                .reset_index()
                .merge(centros_df, on="ponto_id")
                .sort_values("ponto_id")
                .reset_index(drop=True))
    pontos = pontos[["ponto_id", "lat", "lon", "estados", "n_usinas", "capacidade_mw",
                     "distancia_media_km", "distancia_max_km"]]
    mapa = u[["id_ons", "nom_usina_conjunto", "id_estado", "lat", "lon", "capacidade_mw",
              "ponto_id", "distancia_km"]].reset_index(drop=True)
    return pontos, mapa


# --------------------------------------------------------------------------
# Download (com cache em disco)
# --------------------------------------------------------------------------
def _janela_utc() -> tuple[str, str]:
    """O dia em Brasília vai de 03h UTC a 02h UTC do dia seguinte, então a
    consulta em UTC termina um dia depois de FIM."""
    fim_utc = (pd.Timestamp(C.FIM) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    return C.INICIO, fim_utc


def parametros_api(lat: float, lon: float) -> dict:
    inicio, fim = _janela_utc()
    return {
        "latitude": f"{lat:.4f}",
        "longitude": f"{lon:.4f}",
        "start_date": inicio,
        "end_date": fim,
        "hourly": C.VARIAVEL_VENTO,
        "wind_speed_unit": "ms",
        "timezone": "GMT",
        "models": C.MODELO_CLIMA,
    }


def arquivo_cache(lat: float, lon: float):
    inicio, fim = _janela_utc()
    return C.DIR_CLIMA_RAW / f"{C.MODELO_CLIMA}_{C.VARIAVEL_VENTO}_{lat:.4f}_{lon:.4f}_{inicio}_{fim}.json"


def baixar_vento(pontos: pd.DataFrame, pausa_s: float = 3.0) -> None:
    """Baixa o vento horário de cada ponto que ainda não está no cache.

    Uma requisição por ponto: 5 anos de dados horários contam como ~130
    chamadas no limite da API gratuita (600/min, 10 mil/dia). Em caso de
    HTTP 429 o script espera 65 s e tenta de novo."""
    import requests

    C.DIR_CLIMA_RAW.mkdir(parents=True, exist_ok=True)
    for p in pontos.itertuples():
        destino = arquivo_cache(p.lat, p.lon)
        if destino.exists() and _resposta_valida(destino.read_text(encoding="utf-8")):
            continue
        for tentativa in range(1, 6):
            r = requests.get(C.URL_OPENMETEO, params=parametros_api(p.lat, p.lon), timeout=180)
            if r.status_code == 429:
                print(f"{p.ponto_id}: limite da API atingido, aguardando 65 s")
                time.sleep(65)
                continue
            # A API às vezes responde 200 com uma mensagem de erro em texto
            # (ex.: "timeoutReached"); só grava respostas JSON completas.
            if r.ok and _resposta_valida(r.text):
                destino.write_text(r.text, encoding="utf-8")
                print(f"{p.ponto_id}: vento baixado ({len(r.content) / 1e3:.0f} kB)")
                break
            print(f"{p.ponto_id}: resposta inválida (tentativa {tentativa}): {r.text[:80]!r}")
            time.sleep(10 * tentativa)
        else:
            raise RuntimeError(f"não foi possível baixar o vento do ponto {p.ponto_id}")
        time.sleep(pausa_s)


def _resposta_valida(texto: str) -> bool:
    try:
        bruto = json.loads(texto)
        return len(bruto["hourly"]["time"]) == len(bruto["hourly"][C.VARIAVEL_VENTO]) > 0
    except (ValueError, KeyError, TypeError):
        return False


# --------------------------------------------------------------------------
# Tratamento
# --------------------------------------------------------------------------
def vento_horario(pontos: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Lê o cache e devolve a tabela tidy ponto-hora em horário de Brasília."""
    partes, qa = [], {}
    for p in pontos.itertuples():
        bruto = json.loads(arquivo_cache(p.lat, p.lon).read_text(encoding="utf-8"))
        if bruto.get("hourly_units", {}).get(C.VARIAVEL_VENTO) not in ("m/s",):
            raise ValueError(f"unidade inesperada no ponto {p.ponto_id}: {bruto.get('hourly_units')}")
        horas = pd.to_datetime(bruto["hourly"]["time"], utc=True)
        partes.append(pd.DataFrame({
            "ponto_id": p.ponto_id,
            "din_instante": horas.tz_convert(C.FUSO_ONS).tz_localize(None),
            "vento_100m_ms": pd.to_numeric(pd.Series(bruto["hourly"][C.VARIAVEL_VENTO]), errors="coerce"),
            "elevacao_grade_m": bruto.get("elevation"),
        }))
    v = pd.concat(partes, ignore_index=True)
    inicio, fim = pd.Timestamp(C.INICIO), pd.Timestamp(C.FIM) + pd.Timedelta(hours=23)
    v = v[v["din_instante"].between(inicio, fim)].drop_duplicates(["ponto_id", "din_instante"])

    qa["horas_por_ponto"] = int(v.groupby("ponto_id").size().min())
    qa["vento_ausente"] = int(v["vento_100m_ms"].isna().sum())
    fora = (v["vento_100m_ms"] < 0) | (v["vento_100m_ms"] > 50)
    qa["vento_fora_da_faixa_0_50ms"] = int(fora.sum())
    v.loc[fora, "vento_100m_ms"] = np.nan
    # lacunas curtas (até 3 h) são interpoladas no tempo; maiores ficam ausentes
    v = v.sort_values(["ponto_id", "din_instante"])
    v["vento_100m_ms"] = v.groupby("ponto_id")["vento_100m_ms"].transform(
        lambda s: s.interpolate(limit=3, limit_area="inside"))
    qa["vento_ausente_apos_interpolacao"] = int(v["vento_100m_ms"].isna().sum())
    return v.reset_index(drop=True), qa


def vento_diario_pontos(v: pd.DataFrame) -> pd.DataFrame:
    """Média diária por ponto do vento e do vento ao cubo.

    O cubo entra porque a potência disponível no vento cresce com v³;
    a média de v³ preserva o efeito das rajadas que a média de v suaviza."""
    v = v.assign(data=v["din_instante"].dt.normalize(), vento3=v["vento_100m_ms"] ** 3)
    return (v.groupby(["ponto_id", "data"])
              .agg(vento_100m_ms=("vento_100m_ms", "mean"),
                   vento_100m_cubo=("vento3", "mean"),
                   horas=("vento_100m_ms", "count"))
              .reset_index())


def indice_vento_ne_horario(vento_h: pd.DataFrame, usinas_dia: pd.DataFrame,
                            mapa: pd.DataFrame) -> pd.DataFrame:
    """Vento horário do NE: média dos pontos ponderada pela capacidade do dia.

    Usado na análise por hora do dia (etapa 3); não entra na base diária."""
    cap_ponto = (usinas_dia.merge(mapa[["id_ons", "ponto_id"]], on="id_ons", how="inner")
                           .groupby(["data", "ponto_id"])["capacidade_mw"].sum()
                           .rename("peso_mw").reset_index())
    x = (vento_h.assign(data=vento_h["din_instante"].dt.normalize())
                .merge(cap_ponto, on=["data", "ponto_id"], how="inner")
                .dropna(subset=["vento_100m_ms"]))
    x["vento_x_peso"] = x["vento_100m_ms"] * x["peso_mw"]
    h = x.groupby("din_instante")[["vento_x_peso", "peso_mw"]].sum()
    return (h["vento_x_peso"] / h["peso_mw"]).rename("vento_100m_ms").reset_index()


def indice_vento_ne(vento_pontos_dia: pd.DataFrame, usinas_dia: pd.DataFrame,
                    mapa: pd.DataFrame) -> pd.DataFrame:
    """Índice diário do NE: média dos pontos ponderada pela capacidade do dia."""
    cap_ponto = (usinas_dia.merge(mapa[["id_ons", "ponto_id"]], on="id_ons", how="inner")
                           .groupby(["data", "ponto_id"])["capacidade_mw"].sum()
                           .rename("peso_mw").reset_index())
    x = vento_pontos_dia.merge(cap_ponto, on=["data", "ponto_id"], how="inner")
    x = x.dropna(subset=["vento_100m_ms"])

    def media_pond(g):
        w = g["peso_mw"]
        return pd.Series({
            "vento_100m_ms": np.average(g["vento_100m_ms"], weights=w),
            "vento_100m_cubo": np.average(g["vento_100m_cubo"], weights=w),
            # dispersão entre pontos: vento homogêneo na região ou concentrado
            "vento_100m_desvio_entre_pontos": np.sqrt(np.average(
                (g["vento_100m_ms"] - np.average(g["vento_100m_ms"], weights=w)) ** 2, weights=w)),
            "pontos_clima": int(g["ponto_id"].nunique()),
        })

    out = (x.groupby("data")[["vento_100m_ms", "vento_100m_cubo", "peso_mw", "ponto_id"]]
             .apply(media_pond).reset_index())
    out["pontos_clima"] = out["pontos_clima"].astype("int64")
    return out
