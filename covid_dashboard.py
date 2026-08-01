"""
covid_dashboard.py
-------------------
Dashboard COVID-19 (dados OWID) — Streamlit + Snowflake, via Snowpark.

Fluxo (mesmo padrão do exemplo olist_dash.py):
1. Botão "Carregar/Atualizar Dados no Snowflake": baixa o CSV público da OWID
   já filtrado por país/período (evita subir as ~400 mil linhas originais) e
   envia para o Snowflake via session.write_pandas (cria a tabela sozinho).
2. Botão "Carregar Dashboard": lê a tabela de volta do Snowflake e guarda em
   st.session_state para alimentar KPIs, gráficos e a aba de dados brutos.

Pré-requisitos:
- .streamlit/secrets.toml preenchido (ver secrets.toml.example) — seção [snowflake]
- Role com permissão para criar database/schema/tabela (ex.: ACCOUNTADMIN,
  ou uma role customizada com os grants equivalentes)
"""

import streamlit as st
import pandas as pd
import plotly.express as px
from snowflake.snowpark import Session
from datetime import datetime

st.set_page_config(
    page_title="Dashboard COVID-19 — OWID",
    page_icon="🦠",
    layout="wide",
)

st.title("🦠 Dashboard COVID-19 — Our World in Data")
st.caption("Fonte dos dados: Our World in Data · Armazenamento e consulta: Snowflake (via Snowpark)")

URL_OWID = "https://raw.githubusercontent.com/owid/covid-19-data/master/public/data/owid-covid-data.csv"

COLUNAS_OWID = [
    "location", "date", "continent", "new_cases",
    "total_cases", "total_deaths", "people_vaccinated", "population",
]

TABELA = "COVID_DATA"

PAISES_PADRAO = [
    "Brazil", "United States", "India", "Germany", "France",
    "United Kingdom", "Argentina", "Portugal", "Italy", "Japan",
]

# Credenciais (usuário/senha/account/warehouse/role) vêm do .streamlit/secrets.toml.
# Database e schema deste projeto ficam fixos aqui no código — mesma lógica do
# olist_dash.py — assim o app sempre aponta para o banco dele mesmo, mesmo que
# o secrets.toml tenha outros valores (ex.: os defaults de SNOWFLAKE_SAMPLE_DATA
# gerados pelo setup_snowflake.py).
connection_parameters = {
    "user": st.secrets["snowflake"]["user"],
    "password": st.secrets["snowflake"]["password"],
    "account": st.secrets["snowflake"]["account"],
    "warehouse": st.secrets["snowflake"]["warehouse"],
    "role": st.secrets["snowflake"]["role"],
}
DATABASE = "COVID_DB"
SCHEMA = "PUBLIC"


def baixar_e_filtrar(paises, data_inicio, data_fim):
    """Baixa o CSV da OWID (~400 mil linhas) e devolve só o recorte pedido."""
    df = pd.read_csv(URL_OWID, usecols=COLUNAS_OWID, low_memory=False)
    df["date"] = pd.to_datetime(df["date"])

    df = df[
        (df["location"].isin(paises))
        & (df["date"] >= pd.to_datetime(data_inicio))
        & (df["date"] <= pd.to_datetime(data_fim))
    ].copy()

    df = df.dropna(subset=["new_cases", "total_cases"], how="all")
    df["new_cases"] = df["new_cases"].fillna(0)
    df["total_deaths"] = df.groupby("location")["total_deaths"].ffill().fillna(0)
    df["people_vaccinated"] = df.groupby("location")["people_vaccinated"].ffill()
    df = df.sort_values(["location", "date"])

    # Snowpark grava as colunas em maiúsculo por padrão
    df.columns = [c.upper() for c in df.columns]
    return df


# ---------------------------------------------------------------------
# Sidebar — carga de dados
# ---------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Dados")

    paises_carga = st.multiselect(
        "Países a carregar do OWID",
        options=PAISES_PADRAO,
        default=PAISES_PADRAO,
    )
    col_a, col_b = st.columns(2)
    with col_a:
        data_inicio = st.date_input("De", value=datetime(2020, 3, 1))
    with col_b:
        data_fim = st.date_input("Até", value=datetime(2023, 12, 31))

    if st.button("🔄 Carregar/Atualizar Dados no Snowflake", use_container_width=True):
        if not paises_carga:
            st.sidebar.warning("Selecione ao menos um país.")
        else:
            try:
                with st.spinner("Baixando e filtrando dados da OWID..."):
                    df_novo = baixar_e_filtrar(paises_carga, data_inicio, data_fim)
                st.sidebar.success(f"✅ {len(df_novo):,} linhas filtradas (de ~400 mil originais)")

                with st.spinner("Enviando para o Snowflake..."):
                    session = Session.builder.configs(connection_parameters).create()
                    session.sql(f"CREATE DATABASE IF NOT EXISTS {DATABASE}").collect()
                    session.sql(f"USE DATABASE {DATABASE}").collect()
                    session.sql(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}").collect()
                    session.sql(f"USE SCHEMA {SCHEMA}").collect()
                    session.write_pandas(df_novo, TABELA, auto_create_table=True, overwrite=True)
                    session.close()

                st.sidebar.success("✅ Dados atualizados no Snowflake!")
                st.balloons()
            except Exception as e:
                st.sidebar.error(f"❌ Erro ao carregar dados: {e}")

    if st.button("📊 Carregar Dashboard", type="primary", use_container_width=True):
        try:
            with st.spinner("Lendo dados do Snowflake..."):
                session = Session.builder.configs(connection_parameters).create()
                session.sql(f"USE DATABASE {DATABASE}").collect()
                session.sql(f"USE SCHEMA {SCHEMA}").collect()
                df = session.table(TABELA).to_pandas()
                session.close()

            df.columns = df.columns.str.lower()
            df["date"] = pd.to_datetime(df["date"])
            st.session_state["df"] = df
            st.sidebar.success(f"✅ {len(df):,} linhas carregadas")
        except Exception as e:
            st.sidebar.error(f"❌ Erro ao carregar dashboard: {e}")
            st.sidebar.info(
                "💡 Se a tabela ainda não existe, clique primeiro em "
                "'Carregar/Atualizar Dados no Snowflake'."
            )

# ---------------------------------------------------------------------
# Corpo principal — só roda depois que os dados estiverem na sessão
# ---------------------------------------------------------------------
if "df" not in st.session_state:
    st.info(
        "👈 Na barra lateral: clique em **Carregar/Atualizar Dados no Snowflake** "
        "(só na primeira vez ou quando quiser atualizar os países/período) e "
        "depois em **Carregar Dashboard**."
    )
    st.stop()

df = st.session_state["df"]

st.sidebar.divider()
st.sidebar.header("🔍 Filtros de visualização")

paises_disponiveis = sorted(df["location"].unique())
paises_selecionados = st.sidebar.multiselect(
    "Países", options=paises_disponiveis, default=paises_disponiveis
)

data_min, data_max = df["date"].min().date(), df["date"].max().date()
periodo = st.sidebar.slider(
    "Período", min_value=data_min, max_value=data_max, value=(data_min, data_max)
)

if not paises_selecionados:
    st.warning("Selecione ao menos um país na barra lateral.")
    st.stop()

df_filtrado = df[
    (df["location"].isin(paises_selecionados))
    & (df["date"] >= pd.to_datetime(periodo[0]))
    & (df["date"] <= pd.to_datetime(periodo[1]))
]

if df_filtrado.empty:
    st.warning("Nenhum dado para essa combinação de filtros.")
    st.stop()

# ---------------------------------------------------------------------
# KPIs
# ---------------------------------------------------------------------
ultima_data = df_filtrado.groupby("location").tail(1)

total_casos = ultima_data["total_cases"].sum()
total_obitos = ultima_data["total_deaths"].sum()
total_pop = ultima_data["population"].sum()
total_vacinados = ultima_data["people_vaccinated"].sum()
pct_vacinados = (total_vacinados / total_pop * 100) if total_pop else 0

col1, col2, col3 = st.columns(3)
col1.metric("Total de casos (acumulado)", f"{total_casos:,.0f}")
col2.metric("Total de óbitos (acumulado)", f"{total_obitos:,.0f}")
col3.metric("% da população vacinada (1ª dose)", f"{pct_vacinados:.1f}%")

st.divider()

# ---------------------------------------------------------------------
# Abas: Visualizações + Dados brutos
# ---------------------------------------------------------------------
aba_graficos, aba_dados = st.tabs(["📊 Visualizações", "🗂️ Dados Brutos"])

with aba_graficos:
    col_a, col_b = st.columns(2)

    with col_a:
        st.subheader("Evolução de casos novos por país")
        fig_linha = px.line(
            df_filtrado, x="date", y="new_cases", color="location",
            labels={"date": "Data", "new_cases": "Casos novos", "location": "País"},
        )
        st.plotly_chart(fig_linha, use_container_width=True)

    with col_b:
        st.subheader("Total de óbitos por país")
        df_obitos = ultima_data.sort_values("total_deaths", ascending=False)
        fig_barras = px.bar(
            df_obitos, x="location", y="total_deaths", color="location",
            labels={"location": "País", "total_deaths": "Total de óbitos"},
        )
        fig_barras.update_layout(showlegend=False)
        st.plotly_chart(fig_barras, use_container_width=True)

    col_c, col_d = st.columns(2)

    with col_c:
        st.subheader("Proporção de vacinados (1 dose)")
        df_vac = ultima_data.dropna(subset=["people_vaccinated"])
        if df_vac.empty:
            st.info("Sem dados de vacinação para os países/período selecionados.")
        else:
            fig_pizza = px.pie(
                df_vac, names="location", values="people_vaccinated",
                labels={"location": "País", "people_vaccinated": "Pessoas vacinadas (1 dose)"},
            )
            st.plotly_chart(fig_pizza, use_container_width=True)

    with col_d:
        st.subheader("População × Total de casos")
        fig_dispersao = px.scatter(
            ultima_data, x="population", y="total_cases", color="location",
            size="total_cases", hover_name="location",
            labels={"population": "População", "total_cases": "Total de casos"},
        )
        st.plotly_chart(fig_dispersao, use_container_width=True)

with aba_dados:
    st.subheader("Dados brutos filtrados")
    st.dataframe(df_filtrado, use_container_width=True)

    csv = df_filtrado.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="⬇️ Baixar CSV filtrado",
        data=csv,
        file_name=f"covid_dados_filtrados_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
    )

st.divider()
st.caption(
    "Dashboard desenvolvido em Streamlit, com dados hospedados no Snowflake via Snowpark. "
    "Dataset original: Our World in Data (OWID) — COVID-19."
)