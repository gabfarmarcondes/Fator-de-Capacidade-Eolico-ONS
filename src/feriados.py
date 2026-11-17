"""Calendário: fins de semana, feriados nacionais e carnaval.

Os feriados vêm da biblioteca `holidays` (feriados nacionais do Brasil,
categoria pública). O carnaval é ponto facultativo, não feriado, mas reduz
muito a carga do sistema; por isso entra como coluna própria, vinda da
categoria opcional da mesma biblioteca.

Associação aos dados do ONS: pela data em horário de Brasília. Feriados
estaduais e municipais não entram: a carga que afeta o corte de geração
eólica é a do sistema interligado, dominada pelos feriados nacionais.
"""
from __future__ import annotations

import holidays
import pandas as pd

from . import config as C


def calendario(inicio: str = C.INICIO, fim: str = C.FIM) -> pd.DataFrame:
    datas = pd.date_range(inicio, fim, freq="D", name="data")
    anos = range(datas.min().year, datas.max().year + 1)
    nacionais = holidays.Brazil(years=anos)
    opcionais = holidays.Brazil(years=anos, categories=("optional",))
    carnaval = {d for d, nome in opcionais.items() if "Carnaval" in nome}

    cal = pd.DataFrame(index=datas).reset_index()
    dias = cal["data"].dt.date
    cal["ano"] = cal["data"].dt.year
    cal["mes"] = cal["data"].dt.month
    cal["dia_semana"] = cal["data"].dt.dayofweek          # 0 = segunda ... 6 = domingo
    cal["fim_de_semana"] = cal["dia_semana"] >= 5
    cal["feriado_nacional"] = dias.map(lambda d: d in nacionais)
    cal["nome_feriado"] = dias.map(lambda d: nacionais.get(d)).astype("string")
    cal["carnaval"] = dias.map(lambda d: d in carnaval)
    cal["dia_nao_util"] = cal["fim_de_semana"] | cal["feriado_nacional"] | cal["carnaval"]
    # Safra dos ventos no NE: julho a outubro (usada na H1)
    cal["safra_ventos"] = cal["mes"].between(7, 10)
    return cal
