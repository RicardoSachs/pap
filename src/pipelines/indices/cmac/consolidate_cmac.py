
#%%
import os
import sys
from pathlib import Path

project_root = Path(os.getcwd()).parent.parent.parent.parent.resolve()
sys.path.append(str(project_root))

import time
from datetime import datetime
import numpy as np
import pandas as pd
from src.shared.paths import RAW_DIR, STAGING_DIR

mensuales_old_dir = RAW_DIR / 'sbs' / 'cmac' / 'old_template'
mensuales_new_dir = RAW_DIR / 'sbs' / 'cmac' / 'new_template'
staging_dir = STAGING_DIR / 'indices'

mes_map = ['Enero','Febrero','Marzo','Abril','Mayo','Junio','Julio',
           'Agosto','Septiembre','Octubre','Noviembre','Diciembre']
mes_map = {mes:(i+1) for i,mes in enumerate(mes_map)}
mes_map['Setiembre'] = 9

#%%
def parse_old(path, month_map):
   df = pd.read_excel(path)
   m_str, y = df.columns[0].split(' ')[-3::2]
   date = datetime(int(y), month_map[m_str], 1)
   tasa360d_ind = df.iloc[1].str.contains('más de 360 días').tolist().index(True)

   df = df.iloc[2:,[0, tasa360d_ind]]\
   .assign(date = date)\
   .iloc[:,[2,0,1]]

   df.columns = ['fecha', 'caja', 'tasa']

   return df

def parse_new(path, month_map):
    df = pd.read_excel(path)
    m_str, y = df.iloc[2,1].split(' ')[-3::2]
    date = datetime(int(y), month_map[m_str], 1)
    tasa360d_ind = df.iloc[5].str.contains('ás de 360 días').tolist().index(True)
     
    df = df.iloc[6:(df.iloc[:,1].str.contains('Promedio').tolist().index(True) + 1),
                 [1, tasa360d_ind]]\
                 .assign(date = date)\
                 .iloc[:,[2,0,1]]
    
    df.columns = ['fecha', 'caja', 'tasa']

    return df

#%%
def consolidate_sources():
    old_files = os.listdir(mensuales_old_dir)
    new_files = os.listdir(mensuales_new_dir)

    df_old = [*map(lambda x:parse_old(mensuales_old_dir / x, mes_map), old_files)]
    df_new = [*map(lambda x:parse_new(mensuales_new_dir / x, mes_map), new_files)]

    #return df_old, df_new

    df_all = pd.concat(df_old + df_new , ignore_index = True)\
    .sort_values('fecha')\
    .reset_index(drop = True)

    return df_all

#%% 
df_caja = consolidate_sources().drop_duplicates()

# %%
df_caja.caja = np.where(df_caja.caja.str.contains('CMAC') | df_caja.caja.str.contains('CMCP'),
                        df_caja.caja.str.title()\
                        .str.replace('Cmac', 'CMAC')\
                        .str.replace('Cmcp', 'CMCP')\
                        .str.replace('Del','del')\
                        .str.replace(' (*)',''),
                        df_caja.caja)
df_caja.caja = np.where(df_caja.caja.str.contains('Promedio'),
                        'Promedio',
                        df_caja.caja)

#%%
# df_caja.value_counts('fecha').sort_index().plot()
# df_caja.pivot(index = 'fecha', columns='caja', values='tasa').plot()
df_caja.to_csv(staging_dir / 'cmac.csv', index=False)

#%%
df_prom = df_caja[df_caja['caja'] == 'Promedio']
df_prom.sort_values('fecha', inplace=True)
df_prom['tasa'] = df_prom['tasa'].shift(12) / 100
df_prom = df_prom[df_prom['fecha'].dt.month == 12].tail(10)
(np.prod(1+df_prom.tasa)**0.1-1)*100 #10 years CAGR
