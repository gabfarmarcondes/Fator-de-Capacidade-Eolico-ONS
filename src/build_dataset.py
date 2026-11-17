"""Gera a base diária tidy do FC eólico do Nordeste integrada a vento e feriados.

Uso (na raiz do projeto, com o venv ativo):
    python -m src.build_dataset              # usa os arquivos do ONS já baixados
    python -m src.build_dataset --baixar-ons # baixa antes os meses que faltarem

Saídas:
    data/processed/base_fc_eolico_ne_diario.parquet   base final (1 linha = 1 dia)
    data/interim/fc_eolico_ne_horario.parquet         série horária do NE
    data/interim/usinas_dia.parquet                   usina x dia
    data/interim/usinas_pontos_clima.parquet          usina -> ponto de clima
    data/interim/pontos_clima.parquet                 pontos de clima
    data/interim/vento_pontos_diario.parquet          ponto x dia
    reports/qualidade_dados.json                      contagens de cada tratamento
"""
from __future__ import annotations

import argparse
import json
import platform

import pandas as pd

from . import clima, feriados, ons
from . import config as C


def _salvar(df: pd.DataFrame, caminho) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(caminho, index=False)
    print(f"  -> {caminho.relative_to(C.RAIZ)} ({len(df):,} linhas)")


def validar(base: pd.DataFrame) -> dict:
    """Verificações da base final. Falha alto se algo essencial quebrar."""
    datas_esperadas = pd.date_range(C.INICIO, C.FIM, freq="D")
    assert base["data"].is_unique, "datas duplicadas na base final"
    assert len(base) == len(datas_esperadas), "a base não cobre todos os dias do período"
    assert base["fc"].between(0, 1).all(), "FC diário fora de [0, 1]"
    assert base[["vento_100m_ms", "feriado_nacional"]].notna().all().all(), "vento ou calendário ausente"
    return {
        "dias": len(base),
        "dias_qualidade_ok": int(base["qualidade_ok"].sum()),
        "fc_min": round(float(base["fc"].min()), 4),
        "fc_max": round(float(base["fc"].max()), 4),
        "colunas": list(base.columns),
    }


def main(baixar_ons: bool = False) -> pd.DataFrame:
    qa: dict = {"periodo": [C.INICIO, C.FIM], "python": platform.python_version(),
                "pandas": pd.__version__}

    if baixar_ons:
        print("1/6 Baixando arquivos do ONS que faltam")
        ons.baixar_ons()

    print("2/6 Lendo e limpando os dados do ONS (eólicas do Nordeste)")
    bruto, qa["leitura_ons"] = ons.ler_ons()
    limpo, qa["limpeza_ons"] = ons.limpar(bruto)
    del bruto
    usinas = ons.tabela_usinas(limpo)
    horario = ons.serie_horaria(limpo)
    usinas_dia = ons.usina_dia(limpo)
    diario = ons.serie_diaria(horario)
    qa["serie_horaria"] = {
        "horas": len(horario),
        "horas_sem_dado": int(horario["fc"].isna().sum()),
        "cobertura_min": round(float(horario["cobertura"].min()), 4),
    }
    del limpo

    print("3/6 Definindo pontos de clima e baixando o vento (Open-Meteo / ERA5)")
    pontos, mapa = clima.definir_pontos(usinas)
    clima.baixar_vento(pontos)
    vento_h, qa["vento"] = clima.vento_horario(pontos)
    vento_pd = clima.vento_diario_pontos(vento_h)
    indice = clima.indice_vento_ne(vento_pd, usinas_dia, mapa)
    cap = mapa["capacidade_mw"]
    qa["pontos_clima"] = {
        "n_pontos": len(pontos),
        "distancia_max_km": float(mapa["distancia_km"].max()),
        "capacidade_ate_50km": round(float(cap[mapa["distancia_km"] <= 50].sum() / cap.sum()), 3),
    }

    print("4/6 Montando o calendário (holidays)")
    cal = feriados.calendario()

    print("5/6 Integrando as fontes por data")
    base = (diario.merge(indice, on="data", how="left", validate="one_to_one")
                  .merge(cal, on="data", how="left", validate="one_to_one"))
    base = base[[
        "data", "ano", "mes", "dia_semana",
        "fc", "geracao_mwmed", "capacidade_mw", "n_usinas", "horas_com_dado", "cobertura", "qualidade_ok",
        "vento_100m_ms", "vento_100m_cubo", "vento_100m_desvio_entre_pontos", "pontos_clima",
        "fim_de_semana", "feriado_nacional", "nome_feriado", "carnaval", "dia_nao_util", "safra_ventos",
    ]]
    qa["base_final"] = validar(base)

    print("6/6 Salvando")
    _salvar(base, C.BASE_FINAL)
    _salvar(horario, C.DIR_INTERIM / "fc_eolico_ne_horario.parquet")
    _salvar(usinas_dia, C.DIR_INTERIM / "usinas_dia.parquet")
    _salvar(mapa, C.DIR_INTERIM / "usinas_pontos_clima.parquet")
    _salvar(pontos, C.DIR_INTERIM / "pontos_clima.parquet")
    _salvar(vento_pd, C.DIR_INTERIM / "vento_pontos_diario.parquet")
    C.RELATORIO_QUALIDADE.parent.mkdir(parents=True, exist_ok=True)
    C.RELATORIO_QUALIDADE.write_text(json.dumps(qa, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  -> {C.RELATORIO_QUALIDADE.relative_to(C.RAIZ)}")
    return base


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--baixar-ons", action="store_true", help="baixa os meses do ONS que faltarem")
    main(baixar_ons=parser.parse_args().baixar_ons)
