import streamlit as st
import pandas as pd
import os
from datetime import datetime
import uuid
from fpdf import FPDF
import plotly.express as px
import re
from streamlit_gsheets import GSheetsConnection
import time

# --- CONFIGURAÇÃO VISUAL ---
st.set_page_config(page_title="Edifício San Rafael", layout="wide", page_icon="🏢")

# --- CONFIGURAÇÃO DA CONEXÃO E URL ---
# ⚠️ IMPORTANTE: Substitua pelo link da sua planilha se mudar
url_planilha = "https://docs.google.com/spreadsheets/d/1pwcXngnXhtmcxi0ucfl_ajKza5V-Ij_PgQ6Ce6jFpLM/edit?usp=sharing"

# Nomes exatos das abas
WORKSHEET_DADOS = "Dados"
WORKSHEET_CONFIG = "Config"

# --- ARQUITETURA DE PASTAS (Apenas para PDFs temporários) ---
PASTA_RELATORIOS = 'relatorios'
os.makedirs(PASTA_RELATORIOS, exist_ok=True)

# --- FUNÇÕES BÁSICAS ---
def forcar_numero_bruto(valor):
    try:
        if pd.isna(valor): return 0.0
        s_val = str(valor).strip()
        s_val = s_val.replace("R$", "").replace("r$", "").strip()
        if ',' in s_val and '.' in s_val: 
            s_val = s_val.replace('.', '').replace(',', '.')
        elif ',' in s_val: 
            s_val = s_val.replace(',', '.')
        s_val = re.sub(r'[^\d\.-]', '', s_val)
        if not s_val: return 0.0
        return float(s_val)
    except:
        return 0.0

def get_conexao():
    return st.connection("gsheets", type=GSheetsConnection)

def carregar_dados():
    conn = get_conexao()
    try:
        df = conn.read(worksheet=WORKSHEET_DADOS, ttl=0)
        cols_esperadas = ["ID", "Data", "Tipo", "Categoria", "Unidade", "Descrição", "Valor", "Status"]
        if df.empty or len(df.columns) < 2:
            return pd.DataFrame(columns=cols_esperadas)
        
        df["ID"] = df["ID"].astype(str)
        df["ID"] = df["ID"].apply(lambda x: str(uuid.uuid4()) if pd.isna(x) or x == "nan" or x == "" else x)
        df["Data"] = pd.to_datetime(df["Data"], errors='coerce')
        df = df.dropna(subset=["Data"])
        df["Valor"] = df["Valor"].apply(forcar_numero_bruto)
        df["Categoria"] = df["Categoria"].fillna("Lançamento Avulso")
        df["Descrição"] = df["Descrição"].fillna("")
        df["Unidade"] = df["Unidade"].astype(str).str.strip()
        
        mask_divida = (df["Tipo"] == "Entrada") & (df["Valor"] < -0.01)
        df.loc[mask_divida, "Categoria"] = "Ajuste/Gorjeta"
            
        return df
    except Exception as e:
        return pd.DataFrame(columns=["ID", "Data", "Tipo", "Categoria", "Unidade", "Descrição", "Valor", "Status"])

def salvar_dados(df):
    conn = get_conexao()
    if not df.empty:
        df_save = df.copy()
        df_save["Data"] = pd.to_datetime(df_save["Data"]).dt.strftime('%Y-%m-%d')
        conn.update(data=df_save, worksheet=WORKSHEET_DADOS)
        st.cache_data.clear()

def carregar_config():
    conn = get_conexao()
    try:
        return conn.read(worksheet=WORKSHEET_CONFIG, ttl=0).fillna("")
    except:
        return pd.DataFrame({"Categorias": [], "Unidades": []})

def salvar_config(df):
    conn = get_conexao()
    conn.update(data=df, worksheet=WORKSHEET_CONFIG)
    st.cache_data.clear()
    st.toast("Configurações salvas!", icon="⚙️")

def forcar_numero(valor):
    return forcar_numero_bruto(valor)

def formatar_real(valor):
    texto = f"R$ {valor:,.2f}"
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")

# --- REGRAS DE RELATÓRIO (BLINDADA) ---
def _mask_extras_rateio(df):
    if df.empty: return pd.Series([], dtype=bool)
    
    # 1. Proteção: Se for Rateio de Água/Luz, NUNCA é Extra
    mask_protecao_rateio = df["Categoria"].astype(str).str.contains("Rateio", case=False, na=False)
    
    # 2. Identificação
    desc = df["Descrição"].astype(str)
    regex_pattern = r"\(\s*[\[\'\"]*(?:Todos|Só Salas|Só Aptos|So Salas|So Aptos|Sala|Apto|Unidade)"
    mask_alvo = desc.str.contains(regex_pattern, case=False, regex=True, na=False)
    mask_cat = df["Categoria"].astype(str).str.contains("Taxa|Extra|Obras|Melhorias|Manutenção", case=False, na=False)
    mask_base = (df["Tipo"] == "Entrada")
    
    # É Extra se: (Bateu Regex OU Categoria) E (NÃO é Rateio Protegido)
    return mask_base & (mask_alvo | mask_cat) & (~mask_protecao_rateio)

# --- PDF (SIMPLIFICADO E CORRIGIDO) ---
def gerar_relatorio_prestacao(df_completo, mes_num, mes_nome, ano_ref, lista_unis_config):
    df_completo["Data"] = pd.to_datetime(df_completo["Data"])
    
    if ano_ref == "Todos":
        data_inicio_corte = pd.Timestamp.min
        df_mes = df_completo.copy()
        titulo = "Relatório Geral - Todo o Período"
        nome_arquivo = "Relatorio_Geral_Todos.pdf"
    else:
        if mes_num == 13: 
            data_inicio_corte = pd.Timestamp(year=ano_ref, month=1, day=1)
            df_mes = df_completo[df_completo["Data"].dt.year == ano_ref]
            titulo = f"Relatório Anual - {ano_ref}"
            nome_arquivo = f"Relatorio_Anual_{ano_ref}.pdf"
        else:
            data_inicio_corte = pd.Timestamp(year=ano_ref, month=mes_num, day=1)
            df_mes = df_completo[(df_completo["Data"].dt.year == ano_ref) & (df_completo["Data"].dt.month == mes_num)]
            titulo = f"Relatório de Prestação de Contas - {mes_nome}/{ano_ref}"
            nome_arquivo = f"Relatorio_{mes_nome}_{ano_ref}.pdf"
        
    unis_sala = [u for u in lista_unis_config if "Sala" in u]
    unis_apto = [u for u in lista_unis_config if "Apto" in u]
    qtd_salas = len(unis_sala) if len(unis_sala) > 0 else 1
    qtd_aptos = len(unis_apto) if len(unis_apto) > 0 else 1

    # Cálculos de Saldo Anterior
    df_ant = df_completo[df_completo["Data"] < data_inicio_corte]
    df_ant_norm = df_ant[~df_ant["Categoria"].str.contains("Saldo Inicial", case=False, na=False)]
    
    ant_entradas = df_ant_norm[df_ant_norm["Tipo"]=="Entrada"]["Valor"].sum()
    ant_saidas = df_ant_norm[df_ant_norm["Tipo"]=="Saída"]["Valor"].sum()
    # No saldo anterior, mantemos a lógica antiga de descontar extras apenas se não houver saída correspondente?
    # Para simplificar e não quebrar o passado, vamos assumir fluxo de caixa simples: Entrou - Saiu.
    saldo_op_ant = ant_entradas - ant_saidas
    
    val_inicial = df_completo[df_completo["Categoria"].str.contains("Saldo Inicial", case=False, na=False)]["Valor"].sum()
    saldo_anterior_exibicao = saldo_op_ant + val_inicial
    
    df_mes_entradas = df_mes[(df_mes["Tipo"]=="Entrada") & (~df_mes["Categoria"].str.contains("Saldo Inicial", case=False, na=False))]

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', size=14)
    pdf.cell(190, 8, txt="EDIFÍCIO SAN RAFAEL", ln=1, align="C")
    pdf.set_font("Arial", size=11)
    pdf.cell(190, 6, txt=titulo, ln=1, align="C")
    pdf.line(10, 26, 200, 26)
    pdf.ln(4)

    # 1. SAÍDAS
    df_saidas_mes = df_mes[df_mes["Tipo"]=="Saída"]
    
    mask_agua = df_saidas_mes["Categoria"].str.contains("Água", case=False) & ~df_saidas_mes["Categoria"].str.contains("Cx|Caixa|Conserto", case=False)
    mask_luz = df_saidas_mes["Categoria"].str.contains("Luz", case=False) & ~df_saidas_mes["Categoria"].str.contains("Conserto", case=False)
    mask_limpeza = df_saidas_mes["Categoria"].str.contains("Limpeza", case=False) & ~df_saidas_mes["Categoria"].str.contains("Cx|Caixa|Conserto|Manutenção", case=False)

    gastos_agua = df_saidas_mes[mask_agua]["Valor"].sum()
    gastos_luz = df_saidas_mes[mask_luz]["Valor"].sum()
    gastos_limp = df_saidas_mes[mask_limpeza]["Valor"].sum()
    
    # Todas as outras saídas (incluindo as Obras/Extras geradas pela calculadora) caem aqui
    df_outros_manuais = df_saidas_mes[~(mask_agua | mask_luz | mask_limpeza)]
    total_outros_manuais = df_outros_manuais["Valor"].sum()

    # NOTA: Removemos a lógica de "total_extras_espelhados" para não duplicar despesas.
    # Agora confiamos que a saída foi lançada (manualmente ou pela calculadora).

    total_saidas_final = gastos_agua + gastos_luz + gastos_limp + total_outros_manuais

    pdf.set_font("Arial", 'B', size=10)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(190, 6, "1. DESPESAS REALIZADAS (SAÍDAS DO CAIXA)", 1, 1, 'L', 1)
    pdf.set_font("Arial", size=9)
    pdf.cell(140, 5, "Água + Esgoto", 1); pdf.cell(50, 5, formatar_real(gastos_agua), 1, 1, 'R')
    pdf.cell(140, 5, "Luz (Área Comum)", 1); pdf.cell(50, 5, formatar_real(gastos_luz), 1, 1, 'R')
    pdf.cell(140, 5, "Limpeza Prédio", 1); pdf.cell(50, 5, formatar_real(gastos_limp), 1, 1, 'R')
    
    if not df_outros_manuais.empty:
        for desc, val in df_outros_manuais.groupby("Descrição")["Valor"].sum().items():
            # Exibe a descrição real da saída (ex: Conserto Portão)
            pdf.cell(140, 5, str(desc), 1); pdf.cell(50, 5, formatar_real(val), 1, 1, 'R')
            
    pdf.set_font("Arial", 'B', size=9)
    pdf.cell(140, 5, "TOTAL SAÍDAS:", 1); pdf.cell(50, 5, formatar_real(total_saidas_final), 1, 1, 'R')
    pdf.ln(3)

    # 4. OUTRAS RECEITAS
    mask_outras_receitas = (
        (df_mes["Tipo"] == "Entrada")
        & (df_mes["Valor"] > 0.01)
        & (~df_mes["Categoria"].astype(str).str.contains("Saldo Inicial", case=False, na=False))
        & (~df_mes["Categoria"].astype(str).str.contains("Rateio|Fundo", case=False, regex=True, na=False))
        & (~_mask_extras_rateio(df_mes))
    )
    df_outras_receitas = df_mes[mask_outras_receitas]
    if not df_outras_receitas.empty:
        pdf.set_font("Arial", 'B', size=10)
        pdf.set_fill_color(240, 240, 240)
        pdf.cell(190, 6, "4. OUTRAS RECEITAS (ENTRADAS AVULSAS)", 1, 1, 'L', 1)
        pdf.set_font("Arial", size=9)
        grp_rec = df_outras_receitas.groupby(["Descrição"])["Valor"].sum()
        for (desc), val in grp_rec.items():
            label = str(desc).strip() if not pd.isna(desc) else ""
            pdf.cell(140, 5, label, 1); pdf.cell(50, 5, formatar_real(val), 1, 1, 'R')
        pdf.set_font("Arial", 'B', size=9)
        pdf.cell(140, 5, "TOTAL OUTRAS RECEITAS:", 1); pdf.cell(50, 5, formatar_real(df_outras_receitas["Valor"].sum()), 1, 1, 'R')
        pdf.ln(3)

    def bloco_detalhado(titulo, tipo_unidade, qtd, agua_pct, usa_luz_limp, lista_unidades_grupo):
        pdf.set_fill_color(230, 230, 230)
        df_u = df_mes[(df_mes["Tipo"]=="Entrada") & (df_mes["Unidade"].str.contains(tipo_unidade))]
        total_geral_bloco = df_u["Valor"].sum()
        
        # Estimativas para exibição (apenas informativo)
        val_agua_total_grupo = gastos_agua * agua_pct
        unit_agua = val_agua_total_grupo / qtd if qtd > 0 else 0
        val_luz_grupo = gastos_luz if usa_luz_limp else 0
        unit_luz = val_luz_grupo / qtd if qtd > 0 else 0
        val_limp_grupo = gastos_limp if usa_luz_limp else 0
        unit_limp = val_limp_grupo / qtd if qtd > 0 else 0
        total_fundo_recebido = df_u[df_u["Categoria"] == "Fundo de Reserva"]["Valor"].sum()
        unit_fundo = total_fundo_recebido / qtd if qtd > 0 else 0
        
        # Extras identificados
        df_extras = df_u[_mask_extras_rateio(df_u)]
        unit_extra_estimado = df_extras["Valor"].sum() / qtd if qtd > 0 else 0
        
        df_ajustes_all = df_u[df_u["Categoria"].str.contains("Ajuste")]
        valor_cota_final = unit_agua + unit_luz + unit_limp + unit_fundo + unit_extra_estimado

        pdf.set_font("Arial", 'B', size=10)
        pdf.cell(130, 6, titulo, 1, 0, 'L', 1)
        pdf.set_text_color(0, 0, 150)
        pdf.cell(60, 6, f"Valor Médio: {formatar_real(valor_cota_final)}", 1, 1, 'R', 1)
        pdf.set_text_color(0, 0, 0)

        pdf.set_font("Arial", 'B', size=8)
        pdf.cell(190, 5, "COMPOSIÇÃO (Rateio + Fundo + Extras)", 0, 1, 'L')
        pdf.set_font("Arial", size=8)
        pdf.cell(140, 4, f"{int(agua_pct*100)}% Água/Esgoto", "B"); pdf.cell(50, 4, formatar_real(val_agua_total_grupo), "B", 1, 'R')
        if usa_luz_limp:
            pdf.cell(140, 4, f"Luz e Limpeza", "B"); pdf.cell(50, 4, formatar_real(val_luz_grupo + val_limp_grupo), "B", 1, 'R')
        if total_fundo_recebido > 0:
            pdf.cell(140, 4, f"Fundo de Reserva", "B"); pdf.cell(50, 4, formatar_real(total_fundo_recebido), "B", 1, 'R')
        
        if not df_extras.empty:
            pdf.ln(1); pdf.set_font("Arial", 'B', size=8); pdf.cell(190, 5, "ARRECADAÇÃO DE EXTRAS", 0, 1, 'L'); pdf.set_font("Arial", size=8)
            # Agrupa extras por descrição para mostrar quanto entrou
            extras_group = df_extras.groupby("Descrição")["Valor"].sum().reset_index()
            for _, row in extras_group.iterrows():
                # Limpa o nome para ficar bonito
                nome = re.sub(r"[\[\]']", "", str(row['Descrição'])).replace("Extra: ", "").strip().split("(")[0].strip()
                pdf.cell(140, 4, f"{nome}", "B"); pdf.cell(50, 4, formatar_real(row['Valor']), "B", 1, 'R')
        
        pdf.ln(2)
        pdf.set_font("Arial", 'B', size=8)
        pdf.set_fill_color(220, 220, 220)
        pdf.cell(40, 5, "UNIDADE", 1, 0, 'C', 1)
        pdf.cell(40, 5, "VALOR PAGO", 1, 0, 'C', 1)
        pdf.cell(110, 5, "SITUAÇÃO / OBS", 1, 1, 'C', 1)
        pdf.set_font("Arial", size=8)

        for unidade_nome in lista_unidades_grupo:
            entradas_uni = df_u[df_u["Unidade"] == unidade_nome]["Valor"].sum()
            status_txt = ""; cor_texto = (0, 0, 0)
            if entradas_uni >= (valor_cota_final - 0.10):
                status_txt = "Pagamento Integral"; cor_texto = (0, 100, 0)
            elif entradas_uni > 0:
                status_txt = f"Parcial"; cor_texto = (200, 100, 0)
            else:
                status_txt = "EM ABERTO"; cor_texto = (180, 0, 0)
            pdf.set_text_color(0, 0, 0); pdf.cell(40, 5, f"  {unidade_nome}", 1); pdf.cell(40, 5, formatar_real(entradas_uni), 1, 0, 'R')
            pdf.set_text_color(*cor_texto); pdf.cell(110, 5, f"  {status_txt}", 1, 1)
        
        pdf.set_text_color(0, 0, 0); pdf.ln(1); pdf.set_font("Arial", 'B', size=9)
        pdf.cell(140, 6, "TOTAL ARRECADADO GRUPO:", 0, 0, 'R'); pdf.cell(50, 6, formatar_real(total_geral_bloco), 1, 1, 'R')
        pdf.ln(3)

    bloco_detalhado("2. ARRECADAÇÃO: SALAS", "Sala", qtd_salas, 0.35, False, unis_sala)
    bloco_detalhado("3. ARRECADAÇÃO: APARTAMENTOS", "Apto", qtd_aptos, 0.65, True, unis_apto)

    entradas_periodo = df_mes_entradas["Valor"].sum()
    saldo_final_caixa = saldo_anterior_exibicao + entradas_periodo - total_saidas_final

    pdf.set_font("Arial", 'B', size=11)
    pdf.cell(190, 8, "RESUMO DE CAIXA (FLUXO)", 0, 1, 'C')
    pdf.set_font("Arial", 'B', size=9)
    pdf.cell(100, 6, "DESCRIÇÃO", 1, 0, 'C', 1); pdf.cell(90, 6, "VALOR", 1, 1, 'C', 1)
    pdf.set_text_color(100, 100, 100); pdf.cell(100, 6, "SALDO ANTERIOR", 1); pdf.cell(90, 6, formatar_real(saldo_anterior_exibicao), 1, 1, 'R')
    pdf.set_text_color(0, 100, 0); pdf.cell(100, 6, "(+) ENTRADAS TOTAIS", 1); pdf.cell(90, 6, formatar_real(entradas_periodo), 1, 1, 'R')
    pdf.set_text_color(180, 0, 0); pdf.cell(100, 6, "(-) SAÍDAS", 1); pdf.cell(90, 6, formatar_real(total_saidas_final), 1, 1, 'R')
    if saldo_final_caixa >= 0: pdf.set_text_color(0, 0, 200)
    else: pdf.set_text_color(255, 0, 0)
    pdf.cell(100, 6, "(=) SALDO ATUAL EM CAIXA", 1); pdf.cell(90, 6, formatar_real(saldo_final_caixa), 1, 1, 'R')
    pdf.set_text_color(0, 0, 0)
    
    caminho_final = os.path.join(PASTA_RELATORIOS, nome_arquivo)
    pdf.output(caminho_final)
    return caminho_final

# --- APP PRINCIPAL ---
def main():
    st.sidebar.title("🏢 Edifício San Rafael")
    st.sidebar.divider()
    opcao = st.sidebar.radio("Navegar:", ["Calculadora de Rateio", "Extrato (Dashboard)", "Entradas/Saídas Avulsas", "Cadastros"])
    
    df = carregar_dados()
    df_config = carregar_config()
    
    lista_cats = [x for x in df_config["Categorias"].unique() if x != ""] if "Categorias" in df_config.columns else []
    lista_unis = [x for x in df_config["Unidades"].unique() if x != ""] if "Unidades" in df_config.columns else []

    unis_sala = [u for u in lista_unis if "Sala" in u]
    unis_apto = [u for u in lista_unis if "Apto" in u]
    qtd_salas = len(unis_sala) if len(unis_sala) > 0 else 1
    qtd_aptos = len(unis_apto) if len(unis_apto) > 0 else 1

    if opcao == "Calculadora de Rateio":
        st.header("🧮 Calculadora de Rateio")
        st.info(f"Unidades: {qtd_salas} Salas, {qtd_aptos} Apartamentos.")

        with st.container(border=True):
            col1, col2 = st.columns(2)
            data_ref = col1.date_input("Data de Vencimento/Referência", datetime.today())
            c_agua, c_luz, c_limp = st.columns(3)
            total_agua = c_agua.number_input("Total Água (R$)", min_value=0.0, format="%.2f")
            total_luz = c_luz.number_input("Total Luz (R$)", min_value=0.0, format="%.2f")
            total_limp = c_limp.number_input("Total Limpeza (R$)", min_value=0.0, format="%.2f")
            st.divider()
            st.subheader("2. Fundos e Extras")
            cf1, cf2 = st.columns([1, 2])
            val_fundo = cf1.number_input("Fundo de Caixa (Valor Unitário)", min_value=0.0, format="%.2f")
            with cf2:
                st.write("Tabela de Despesas Extras:")
                if 'extras_editor' not in st.session_state:
                    st.session_state['extras_editor'] = pd.DataFrame(columns=["Descrição", "Valor Total", "Ratear Para"])
                
                df_extras_input = st.data_editor(
                    st.session_state['extras_editor'],
                    num_rows="dynamic",
                    column_config={
                        "Descrição": st.column_config.TextColumn(required=True, width="medium"),
                        "Valor Total": st.column_config.NumberColumn(format="R$ %.2f", required=True),
                        "Ratear Para": st.column_config.SelectboxColumn(options=["Todos", "Só Salas", "Só Aptos"], required=True, default="Todos")
                    },
                    key="extras_table"
                )
            st.divider()

        rateio_sala = (total_agua * 0.35) / qtd_salas
        rateio_apto = ( (total_agua * 0.65) + total_luz + total_limp ) / qtd_aptos

        if st.button("Calcular e Pré-Visualizar", type="primary"):
            df_extras_clean = df_extras_input.copy()
            if not df_extras_clean.empty:
                df_extras_clean["Valor Total"] = df_extras_clean["Valor Total"].apply(forcar_numero)

            st.session_state['dados_rateio'] = {
                'data': data_ref, 'rs': rateio_sala, 'ra': rateio_apto, 'fundo': val_fundo,
                'extras_df': df_extras_clean,
                'totais': {'agua': total_agua, 'luz': total_luz, 'limp': total_limp}
            }
            
            def calcular_total_extra_por_unidade(tipo_uni, df_ex):
                soma = 0.0
                if df_ex is not None and not df_ex.empty:
                    for _, row in df_ex.iterrows():
                        val = row["Valor Total"]
                        target = str(row.get("Ratear Para", "Todos"))
                        if "Todos" in target: soma += val / (qtd_salas + qtd_aptos)
                        elif "Sala" in target and tipo_uni == "Sala": soma += val / qtd_salas
                        elif "Apto" in target and tipo_uni == "Apto": soma += val / qtd_aptos
                return soma

            extra_sala_val = calcular_total_extra_por_unidade("Sala", df_extras_clean)
            extra_apto_val = calcular_total_extra_por_unidade("Apto", df_extras_clean)

            lista = []
            for uni in unis_sala:
                total_base = rateio_sala + val_fundo + extra_sala_val
                lista.append({"Unidade": uni, "Rateio": rateio_sala, "Fundo": val_fundo, "Extra": extra_sala_val, "Ajuste": 0.0, "Total Devido": total_base, "Valor Pago": total_base, "Status": "Ok"})
            for uni in unis_apto:
                total_base = rateio_apto + val_fundo + extra_apto_val
                lista.append({"Unidade": uni, "Rateio": rateio_apto, "Fundo": val_fundo, "Extra": extra_apto_val, "Ajuste": 0.0, "Total Devido": total_base, "Valor Pago": total_base, "Status": "Ok"})
            
            st.session_state['df_preview'] = pd.DataFrame(lista)

        if 'dados_rateio' in st.session_state and 'df_preview' in st.session_state:
            d = st.session_state['dados_rateio']
            st.divider()
            
            st.subheader("📋 Resumo do Rateio")
            df_prev_temp = st.session_state['df_preview']
            
            edited_df = st.data_editor(
                st.session_state['df_preview'], 
                hide_index=True, 
                column_config={
                    "Rateio": st.column_config.NumberColumn(format="R$ %.2f", disabled=True),
                    "Fundo": st.column_config.NumberColumn(format="R$ %.2f", disabled=True),
                    "Extra": st.column_config.NumberColumn(format="R$ %.2f", disabled=True),
                    "Ajuste": st.column_config.NumberColumn("Ajuste (+/-)", format="R$ %.2f", required=True),
                    "Total Devido": st.column_config.NumberColumn(format="R$ %.2f", disabled=True),
                    "Valor Pago": st.column_config.NumberColumn("Valor Pago", format="R$ %.2f", required=True),
                    "Status": st.column_config.TextColumn(disabled=True)
                }
            )

            recalc = False
            for i, row in edited_df.iterrows():
                base = row["Rateio"] + row["Fundo"] + row["Extra"]
                ajuste = float(row.get("Ajuste", 0.0))
                novo_devido = base + ajuste
                
                if abs(row["Total Devido"] - novo_devido) > 0.01:
                    edited_df.at[i, "Total Devido"] = novo_devido
                    edited_df.at[i, "Valor Pago"] = novo_devido
                    recalc = True
                
                pago = float(edited_df.at[i, "Valor Pago"])
                devido = float(edited_df.at[i, "Total Devido"])
                
                novo_status = "Ok"
                if pago < devido:
                    falta = devido - pago
                    novo_status = f"Pendente (Falta R$ {falta:.2f})"
                elif pago > devido:
                    sobra = pago - devido
                    novo_status = f"Ok (+ R$ {sobra:.2f})"
                if row["Status"] != novo_status:
                    edited_df.at[i, "Status"] = novo_status
                    recalc = True
            
            if recalc:
                st.session_state['df_preview'] = edited_df
                st.rerun()

            # --- BLOCO DE SALVAMENTO CORRIGIDO E SEGURO ---
            if st.button("🚀 Confirmar e Salvar no Arquivo", type="primary"):
                novos = []
                
                # 1. Salva as Entradas dos Moradores (Rateio, Fundo e Extra)
                for i, row in edited_df.iterrows():
                    st_r = row['Status']
                    
                    # Salva Rateio
                    val_rat = row["Rateio"]
                    if val_rat > 0:
                        novos.append({"ID": str(uuid.uuid4()), "Data": d['data'], "Tipo": "Entrada", "Categoria": "Rateio Despesas (Água/Luz)", "Unidade": row['Unidade'], "Descrição": "Rateio", "Valor": val_rat, "Status": st_r})
                    
                    # Salva Fundo
                    val_fun = row["Fundo"]
                    if val_fun > 0:
                        novos.append({"ID": str(uuid.uuid4()), "Data": d['data'], "Tipo": "Entrada", "Categoria": "Fundo de Reserva", "Unidade": row['Unidade'], "Descrição": "Fundo", "Valor": val_fun, "Status": st_r})
                    
                    # Salva Extra (Como entrada, pois o morador está pagando)
                    val_ext = row["Extra"]
                    if val_ext > 0:
                         novos.append({"ID": str(uuid.uuid4()), "Data": d['data'], "Tipo": "Entrada", "Categoria": "Taxa Extra", "Unidade": row['Unidade'], "Descrição": "Taxa Extra (Rateio)", "Valor": val_ext, "Status": st_r})

                    # Salva Ajuste
                    val_aju = float(row["Ajuste"])
                    if val_aju != 0:
                        novos.append({"ID": str(uuid.uuid4()), "Data": d['data'], "Tipo": "Entrada", "Categoria": "Ajuste/Gorjeta", "Unidade": row['Unidade'], "Descrição": "Ajuste Manual", "Valor": val_aju, "Status": st_r})
                    
                    # Diferença de pagamento
                    val_pago = float(row["Valor Pago"])
                    val_devido = float(row["Total Devido"])
                    diferenca = val_pago - val_devido 
                    if abs(diferenca) > 0.01:
                         novos.append({"ID": str(uuid.uuid4()), "Data": d['data'], "Tipo": "Entrada", "Categoria": "Ajuste/Gorjeta", "Unidade": row['Unidade'], "Descrição": "Sobra Pagamento" if diferenca > 0 else "Pendência", "Valor": diferenca, "Status": st_r})

                # 2. Salva Saídas Fixas (Água/Luz)
                if d['totais']['agua'] > 0: novos.append({"ID": str(uuid.uuid4()), "Data": d['data'], "Tipo": "Saída", "Categoria": "Pagto Água/Esgoto", "Unidade": "Condomínio", "Descrição": "Conta Água", "Valor": d['totais']['agua'], "Status": "Ok"})
                if d['totais']['luz'] > 0: novos.append({"ID": str(uuid.uuid4()), "Data": d['data'], "Tipo": "Saída", "Categoria": "Pagto Luz", "Unidade": "Condomínio", "Descrição": "Conta Luz", "Valor": d['totais']['luz'], "Status": "Ok"})
                if d['totais']['limp'] > 0: novos.append({"ID": str(uuid.uuid4()), "Data": d['data'], "Tipo": "Saída", "Categoria": "Pagto Limpeza", "Unidade": "Condomínio", "Descrição": "Limpeza", "Valor": d['totais']['limp'], "Status": "Ok"})
                
                # 3. Salva SAÍDAS da Tabela de Extras (Obras) - CORRIGIDO
                # Isso gera a despesa para abater a entrada do extra
                extras_config_df = d.get('extras_df', pd.DataFrame())
                if not extras_config_df.empty:
                    for _, ext_row in extras_config_df.iterrows():
                        val_total = forcar_numero(ext_row.get("Valor Total", 0.0))
                        desc_extra = ext_row.get("Descrição", "Despesa Extra")
                        if val_total > 0:
                            novos.append({
                                "ID": str(uuid.uuid4()), 
                                "Data": d['data'], 
                                "Tipo": "Saída",  # É SAÍDA!
                                "Categoria": "Obras/Melhorias", 
                                "Unidade": "Condomínio", 
                                "Descrição": desc_extra, 
                                "Valor": val_total, 
                                "Status": "Ok"
                            })
                
                salvar_dados(pd.concat([df, pd.DataFrame(novos)], ignore_index=True))
                
                del st.session_state['dados_rateio']
                del st.session_state['df_preview']
                st.success("✅ Rateio salvo! Entradas e Despesas Extras registradas.")
                time.sleep(1.5)
                st.rerun()

    elif opcao == "Extrato (Dashboard)":
        st.header("📊 Dashboard - Edifício San Rafael")
        if df.empty:
            st.warning("⚠️ Nenhum dado encontrado."); st.stop()

        df["Ano"] = df["Data"].dt.year
        df["Mes"] = df["Data"].dt.month
        
        with st.container(border=True):
            c1, c2, c3 = st.columns(3)
            ano_atual = datetime.today().year
            anos_possiveis = list(range(2020, ano_atual + 2))
            anos_dados = sorted(df["Ano"].dropna().unique().tolist())
            lista_anos = ["Todos"] + sorted(list(set(anos_possiveis + anos_dados)))
            
            idx_ano = 0
            if ano_atual in lista_anos: idx_ano = lista_anos.index(ano_atual)
            
            ano = c1.selectbox("Ano", lista_anos, index=idx_ano)
            meses = {1:"Jan", 2:"Fev", 3:"Mar", 4:"Abr", 5:"Mai", 6:"Jun", 7:"Jul", 8:"Ago", 9:"Set", 10:"Out", 11:"Nov", 12:"Dez", 13:"Todos"}
            mes_key = c2.selectbox("Mês", list(meses.keys()), format_func=lambda x: meses[x], index=12)
            tipo = c3.selectbox("Tipo", ["Todos", "Entrada", "Saída"])

        df_ver = df.copy()
        if ano != "Todos": df_ver = df_ver[df_ver["Ano"] == ano]
        if mes_key != 13: df_ver = df_ver[df_ver["Mes"] == mes_key]
        if tipo != "Todos": df_ver = df_ver[df_ver["Tipo"] == tipo]

        st.subheader("Visão Geral")
        if not df_ver.empty:
            g1, g2 = st.columns(2)
            totais = df_ver.groupby("Tipo")["Valor"].sum().reset_index()
            fig1 = px.bar(totais, x="Tipo", y="Valor", color="Tipo", title="Receitas vs Despesas", color_discrete_map={"Entrada": "#2ecc71", "Saída": "#e74c3c"}, height=300)
            g1.plotly_chart(fig1, use_container_width=True)
            df_ent = df_ver[df_ver["Tipo"]=="Entrada"]
            if not df_ent.empty:
                fig2 = px.pie(df_ent, names="Status", values="Valor", title="Status de Recebimento", color="Status", color_discrete_map={"Ok": "#3498db", "Pendente": "#f1c40f"}, height=300)
                g2.plotly_chart(fig2, use_container_width=True)
        else: st.info("Sem dados para exibir.")
        
        st.divider()
        st.subheader("Detalhamento e Edição")
        
        df_ver_reset = df_ver.reset_index(drop=True)
        
        df_editado = st.data_editor(
            df_ver_reset, hide_index=True, use_container_width=True, num_rows="dynamic",
            column_order=["Data", "Tipo", "Categoria", "Unidade", "Descrição", "Valor", "Status"],
            column_config={
                "Valor": st.column_config.NumberColumn(format="R$ %.2f"),
                "Data": st.column_config.DateColumn(format="DD/MM/YYYY"),
                "Status": st.column_config.SelectboxColumn(options=["Ok", "Pendente"], required=True),
                "Categoria": st.column_config.SelectboxColumn(options=lista_cats, required=True),
                "Unidade": st.column_config.SelectboxColumn(options=lista_unis, required=True),
                "Tipo": st.column_config.SelectboxColumn(options=["Entrada", "Saída"], required=True)
            }
        )

        if st.button("💾 Salvar Alterações", type="primary"):
            df_orig = carregar_dados()
            df_editado["ID"] = df_ver_reset["ID"]
            for i, row in df_editado.iterrows():
                if pd.isna(row["ID"]) or row["ID"] == "": df_editado.at[i, "ID"] = str(uuid.uuid4())
            
            ids_visualizados = df_ver_reset["ID"].tolist()
            ids_editados = df_editado["ID"].tolist()
            ids_para_excluir = set(ids_visualizados) - set(ids_editados)
            
            if ids_para_excluir: df_orig = df_orig[~df_orig["ID"].isin(ids_para_excluir)]
            df_orig = df_orig[~df_orig["ID"].isin(ids_editados)]
            
            df_final = pd.concat([df_orig, df_editado], ignore_index=True)
            salvar_dados(df_final)
            st.rerun()

        st.divider()
        if st.button("📄 Gerar Relatório (PDF)", type="primary"):
            nome_mes = list(meses.keys())[list(meses.values()).index(meses[mes_key])]
            arq = gerar_relatorio_prestacao(df, mes_key, nome_mes, ano, lista_unis)
            with open(arq, "rb") as f:
                st.download_button("Baixar PDF Agora", f, file_name=os.path.basename(arq), type="primary")

    elif opcao == "Entradas/Saídas Avulsas":
        st.header("💸 Lançamentos Avulsos")
        t1, t2 = st.tabs(["Lançamento Avulso", "Definir Saldo Inicial"])
        with t1:
            with st.form("av", clear_on_submit=True):
                c1, c2 = st.columns(2)
                dt = c1.date_input("Data", datetime.today())
                tp = c2.selectbox("Tipo", ["Saída", "Entrada"])
                un = st.selectbox("Unidade / Centro de Custo", ["Condomínio (Geral)"] + lista_unis)
                vl = st.number_input("Valor (R$)", min_value=0.0, format="%.2f")
                ds = st.text_input("Descrição (Ex: Venda de Sucata, Compra de Material)")
                
                if st.form_submit_button("Salvar na Nuvem", type="primary"):
                    if not ds: st.error("Preencha a descrição.")
                    elif vl == 0: st.warning("Valor zerado.")
                    else:
                        novo_dado = pd.DataFrame([{
                            "ID": str(uuid.uuid4()), "Data": dt, "Tipo": tp, "Categoria": "Lançamento Avulso", "Unidade": un, "Descrição": ds, "Valor": vl, "Status": "Ok"
                        }])
                        salvar_dados(pd.concat([df, novo_dado], ignore_index=True))
                        st.success("✅ Salvo com sucesso!"); time.sleep(1.5); st.rerun()

        with t2:
            st.info("Define o saldo inicial histórico (antes de 2020).")
            with st.form("si"):
                dt = st.date_input("Data do Saldo Inicial", datetime(2020, 1, 1))
                vl = st.number_input("Valor Inicial (R$)", min_value=0.0, format="%.2f")
                if st.form_submit_button("Registrar Saldo", type="primary"):
                    novo_dado = pd.DataFrame([{"ID":str(uuid.uuid4()), "Data":dt, "Tipo":"Entrada", "Categoria":"Saldo Inicial", "Unidade":"Caixa", "Descrição":"Saldo Inicial", "Valor":vl, "Status":"Ok"}])
                    salvar_dados(pd.concat([df, novo_dado], ignore_index=True))
                    st.rerun()

    elif opcao == "Cadastros":
        st.header("⚙️ Configurações")
        c1, c2 = st.columns(2)
        d_c = c1.data_editor(pd.DataFrame({"Categoria":lista_cats}), num_rows="dynamic", use_container_width=True, key="ed_cats")
        d_u = c2.data_editor(pd.DataFrame({"Unidade":lista_unis}), num_rows="dynamic", use_container_width=True, key="ed_unis")
        if st.button("Salvar Configurações", type="primary"):
            cats = d_c["Categoria"].tolist(); unis = d_u["Unidade"].tolist()
            max_len = max(len(cats), len(unis))
            cats += [""] * (max_len - len(cats)); unis += [""] * (max_len - len(unis))
            salvar_config(pd.DataFrame({"Categorias": cats, "Unidades": unis}))
            st.rerun()

if __name__ == "__main__":
    main()
