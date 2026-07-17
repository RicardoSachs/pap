# src/pipelines/prices/lva/consolidate_lva.py
# ---------------------------------------------------------------
# LVA index consolidation: parses downloaded LVA daily/historical XML
# files into a single staged indices table.

import os
import sys
from pathlib import Path

project_root = Path(os.getcwd()).resolve()
sys.path.append(str(project_root))
project_root

import time
from datetime import datetime
import numpy as np
import pandas as pd
from utils.paths import RAW_DIR, STAGING_DIR
import xml.etree.ElementTree as ET

diarios_dir = RAW_DIR / 'lva' / 'diarios'
historicos_dir = RAW_DIR / 'lva' / 'historicos'
staging_dir = STAGING_DIR / 'indices'

# Globals
col_name_map = {'Fecha':'fecha',
                'Nombre':'nombre',
                'Ticker':'ticker',
                'Familia':'familia',
                'Quiebre':'quiebre',
                'Índice':'indice',
                'DTD':'retorno',
                'DTD (%)':'retorno',
                'Tir':'tir',
                'Cupón':'cupon',
                'Cupon':'cupon',
                'Monto':'monto',
                'Plazo':'plazo',
                'Duración':'duracion',
                'Emisiones':'emisiones',
                'Precio':'precio',
                'Spread':'spread',
                'Moneda':'moneda'}

col_dtype_map = {'fecha':'datetime64[ns]',
                'indice':'float64',
                'retorno':'float64',
                'tir':'float64',
                'cupon':'float64',
                'monto':'float64',
                'plazo':'float64',
                'duracion':'float64',
                'emisiones':'int64',
                'precio':'float64'}

# Functions
def read_name_csv(path, col_name = 'NOMBRE', delim = '\\', **kwargs):
    """
    Reads the csv and adds the file name as an aditional column
    """
    name = path.split(delim)[-1]
    df = pd.read_csv(path, **kwargs)
    df[col_name] = name
    return df

def name2date(name):
    # Format: Indices_RF_PE_yyyymmdd.csv
    date = name.split('_')[-1].split('.')[0]
    return date

def read_xls(path):
    
    tree = ET.parse(path)
    root = tree.getroot()

    ns = {
        'ss':'urn:schemas-microsoft-com:office:spreadsheet'
    }

    rows = []
    for row in root.findall('.//ss:Row', ns):
        cells = [
            cell.find('ss:Data', ns).text if cell.find('ss:Data', ns) is not None else None for cell in row.findall('ss:Cell', ns)
        ]
        rows.append(cells)
    
    return pd.DataFrame(rows[1:], columns=rows[0])

def bind_df_folder(dir, read_func, **kwargs):
    df_list = []
    
    for xls in os.listdir(dir):
        df = read_func(os.path.join(dir, xls), **kwargs)
        df_list.append(df)

    return pd.concat(df_list)

# Read all xls and consolidate
df_diario = bind_df_folder(diarios_dir, pd.read_csv, thousands = '.', decimal = ',', parse_dates = [14])
df_diario.rename(columns=col_name_map, inplace=True)
df_diario = df_diario[['fecha'] + [col for col in df_diario.columns if col != 'fecha']]
# Reassign sunday to friday
df_diario['fecha'] = np.where(df_diario['fecha'].dt.weekday == 6,
                              df_diario['fecha'] - pd.Timedelta(days=2),
                              df_diario['fecha'])

df_historico = bind_df_folder(historicos_dir, read_xls)
df_historico.rename(columns=col_name_map, inplace=True)
df_historico = df_historico.astype(col_dtype_map)

df_cons = pd.concat(
    [df_diario.drop(columns='spread'),
     df_historico.drop(columns='moneda')])

df_cons = df_cons[df_cons.ticker.isin(['LKPGBA0','LKPCBA0', 'LKPCGA1', 'LKPCGA2'])]
df_cons.to_csv(staging_dir / 'rfpe_lva.csv', index=False)
