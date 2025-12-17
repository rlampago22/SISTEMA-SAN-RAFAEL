import streamlit as st
import pandas as pd
import os
from datetime import datetime
import uuid
from fpdf import FPDF
import plotly.express as px
import re
from streamlit_gsheets import GSheetsConnection

# --- CONFIGURAÇÃO VISUAL ---
st.set_page_config(page_title="Edifício San Rafael", layout="wide", page_icon="🏢")

# --- CONFIGURAÇÃO DA CONEXÃO E URL ---
# ⚠️ O link da planilha virá dos Secrets, mas deixamos uma variável de apoio
# O Streamlit injeta as credenciais automaticamente via st.connection

# Nomes exatos das abas
WORKSHEET_DADOS = "Dados"
WORKSHEET_CONFIG = "Config"

# --- ARQUITETURA DE PASTAS ---
PASTA_RELATORIOS = 'relatorios'
os.makedirs(PASTA_RELATORIOS, exist_ok=True)

# --- FUNÇÕES BÁSICAS ---
def forcar_numero_bruto(valor):
    # Se já for número (int ou float), retorna direto (Google Sheets às vezes manda pronto)
    if isinstance(valor, (int, float)):
        return float(valor)
    
    try:
        if pd.isna(valor): return 0.0
        s_val = str(valor).strip()
        # Remove R$ e espaços
        s_val = s_val.replace("R$", "").replace("r$", "").strip()
        
        # Lógica para detectar formato brasileiro (1.000,00) vs Americano (1,000.00)
        # Se tem vírgula no final (ex: ,00 ou ,5), é BR.
        if ',' in s_val and ('.' in s_val or len(s_val.split(',')[-1]) <= 2):
            s_val = s_val.replace('.', '').replace(',', '.')
        elif ',' in s_val: 
            s_val = s_val.replace(',', '.')
            
        # Remove qualquer coisa que não seja número, ponto ou sinal de menos
        s_val = re.sub(r'[^\d\.-]', '', s_val)
        
        if not s_val: return 0.0
        return float(s_val)
    except:
        return 0.0

def get_conexao():
    # Procura nos secrets primeiro
    return st.connection("gsheets", type=GSheetsConnection)

def carregar_dados():
    conn = get_conexao()
    try:
        # Lê a aba 'Dados'
        df = conn.read(worksheet=WORKSHEET_DADOS)
        
        cols_esperadas = ["ID", "Data", "Tipo", "Categoria", "Unidade", "Descrição", "Valor", "Status"]
        if df.empty or len(df.columns) < 2:
            return pd.DataFrame(columns=cols_esperadas)
        
        # Garante que ID seja string
        df["ID"] = df["ID"].astype(str)
        df["ID"] = df["ID"].apply(lambda x: str(uuid.uuid4()) if pd.isna(x) or x == "nan" or x == "" else x)
            
        df["Data"] = pd.to_datetime(df["Data"], errors='coerce')
        df = df.dropna(subset=["Data"])
        
        # Aplica a correção numérica
        df["Valor"] = df["Valor"].apply(forcar_numero_bruto)
        
        df["Categoria"] = df["Categoria"].fillna("")
        df["Descrição"] = df["Descrição"].fillna("")
        df["Unidade"] = df["Unidade"].astype(str).str.strip()
        
        # Regra de legado
        mask_divida = (df["Tipo"] == "Entrada") & (df["Valor"] < -0.01)
        df.loc[mask_divida, "Categoria"] = "Ajuste/Gorjeta"
            
        return df
    except Exception as e:
        st.error(f"Erro ao conectar com Google Sheets: {e}")
        return pd.DataFrame(columns=["ID", "Data", "Tipo", "Categoria", "Unidade", "Descrição", "Valor", "Status"])

def salvar_dados(df):
    conn = get_conexao()
    if not df.empty:
        df_save = df.copy()
        df_save["Data"] = pd.to_datetime(df_save["Data"]).dt.strftime('%Y-%m-%d')
        conn.update(data=df_save, worksheet=WORKSHEET_DADOS)
        st.toast("Salvo na nuvem com sucesso!", icon="☁️")

def carregar_config():
    conn = get_conexao()
    try:
        df = conn.read(worksheet=WORKSHEET_CONFIG)
        if df.empty:
            dados_iniciais = {
                "Categorias": ["Rateio Despesas (Água/Luz)", "Fundo de Reserva", "Taxa Extra", "Ajuste/Gorjeta", "Saldo Inicial", "Pagto Água/Esgoto", "Pagto Luz", "Pagto Limpeza", "Manutenção", "Obras/Melhorias"],
                "Unidades": ["Apto 101", "Apto 201", "Apto 202", "Apto 301", "Sala 01", "Sala 02", "Sala 03", "Sala 04"]
            }
            return pd.DataFrame(dados_iniciais)
        return df.fillna("")
    except:
        return pd.DataFrame(columns=["Categorias", "Unidades"])

def salvar_config(df):
    conn = get_conexao()
    conn.update(data=df, worksheet=WORKSHEET_CONFIG)
    st.toast("Configurações salvas!", icon="⚙️")

def forcar_numero(valor):
    return forcar_numero_bruto(valor)

def formatar_real(valor):
    texto = f"R$ {valor:,.2f}"
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")

# --- REGRAS DE CLASSIFICAÇÃO ---
def _mask_extras_rateio(df: pd.DataFrame) -> pd.Series:
    if df is None or df.empty:
        return pd.Series([], dtype=bool)

    desc = df["Descrição"].astype(str)
    # Correção do Regex para remover Warning (Grupo de não captura ?:)
    mask_alvo = desc.str.contains(r"\(\s*\['?(?:Todos|Só Salas|Só Aptos|So Salas|So Aptos)", case=False, regex=True, na=False)
    mask_base = (
        (df["Tipo"] == "Entrada")
        & (~df["Categoria"].astype(str).str.contains("Rateio|Fundo|Ajuste|Saldo", case=False, regex=True, na=False))
    )
    return mask_base & mask_alvo

# --- PDF ---
def gerar_relatorio_prestacao(df_completo, mes_num, mes_nome, ano_ref, lista_unis_config):
    # ... (MANTENDO A LÓGICA DO PDF IGUAL - Resumido aqui para caber, mas no seu copie tudo)
    # Vou replicar a função inteira para garantir que funcione ao copiar e colar
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
        
    pasta_destino = PASTA_RELATORIOS
    
    unis_sala = [u for u in lista_unis_config if "Sala" in u]
    unis_apto = [u for u in lista_unis_config if "Apto" in u]
    qtd_salas = len(unis_sala) if len(unis_sala) > 0 else 1
    qtd_aptos = len(unis_apto) if len(unis_apto) > 0 else 1

    df_ant = df_completo[df_completo["Data"] < data_inicio_corte]
    df_ant_norm = df_ant[~df_ant["Categoria"].str.contains("Saldo Inicial", case=False, na=False)]
    
    ant_entradas = df_ant_norm[df_ant_norm["Tipo"]=="Entrada"]["Valor"].sum()
    ant_saidas = df_ant_norm[df_ant_norm["Tipo"]=="Saída"]["Valor"].sum()
    ant_extras = df_ant_norm[_mask_extras_rateio(df_ant_norm)]["Valor"].sum()
    
    saldo_op_ant = ant_entradas - ant_saidas - ant_extras
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
    df_outros_manuais = df_saidas_mes[~(mask_agua | mask_luz | mask_limpeza)]
    total_outros_manuais = df_outros_manuais["Valor"].sum()

    df_extras_arrecadados = df_mes[_mask_extras_rateio(df_mes)]
    extras_para_saida = []
    total_extras_espelhados = 0.0
    if not df_extras_arrecadados.empty:
        grupo_extras = df_extras_arrecadados.groupby("Descrição")["Valor"].sum().reset_index()
        for _, row in grupo_extras.iterrows():
            nome = re.sub(r"[\[\]']", "", str(row['Descrição'])).replace("Extra: ", "").strip().split("(")[0].strip()
            valor = row['Valor']
            extras_para_saida.append((nome, valor))
            total_extras_espelhados += valor

    total_saidas_final = gastos_agua + gastos_luz + gastos_limp + total_outros_manuais + total_extras_espelhados

    pdf.set_font("Arial", 'B', size=10)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(190, 6, "1. DESPESAS REALIZADAS (SAÍDAS DO CAIXA)", 1, 1, 'L', 1)
    pdf.set_font("Arial", size=9)
    pdf.cell(140, 5, "Água + Esgoto", 1); pdf.cell(50, 5, formatar_real(gastos_agua), 1, 1, 'R')
    pdf.cell(140, 5, "Luz (Área Comum)", 1); pdf.cell(50, 5, formatar_real(gastos_luz), 1, 1, 'R')
    pdf.cell(140, 5, "Limpeza Prédio", 1); pdf.cell(50, 5, formatar_real(gastos_limp), 1, 1, 'R')
    if not df_outros_manuais.empty:
        for desc, val in df_outros_manuais.groupby("Descrição")["Valor"].sum().items():
            pdf.cell(140, 5, str(desc), 1); pdf.cell(50, 5, formatar_real(val), 1, 1, 'R')
    for nome, val in extras_para_saida:
        pdf.cell(140, 5, f"{nome} (Extra)", 1); pdf.cell(50, 5, formatar_real(val), 1, 1, 'R')
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
        val_agua_total_grupo = gastos_agua * agua_pct
        unit_agua = val_agua_total_grupo / qtd if qtd > 0 else 0
        val_luz_grupo = gastos_luz if usa_luz_limp else 0
        unit_luz = val_luz_grupo / qtd if qtd > 0 else 0
        val_limp_grupo = gastos_limp if usa_luz_limp else 0
        unit_limp = val_limp_grupo / qtd if qtd > 0 else 0
        total_fundo_recebido = df_u[df_u["Categoria"] == "Fundo de Reserva"]["Valor"].sum()
        unit_fundo = total_fundo_recebido / qtd if qtd > 0 else 0
        df_extras = df_u[~df_u["Categoria"].str.contains("Rateio|Fundo|Ajuste|Saldo")]
        unit_extra_estimado = df_extras["Valor"].sum() / qtd if qtd > 0 else 0
        df_ajustes_all = df_u[df_u["Categoria"].str.contains("Ajuste")]
        valor_cota_final = unit_agua + unit_luz + unit_limp + unit_fundo + unit_extra_estimado

        pdf.set_font("Arial", 'B', size=10)
        pdf.cell(130, 6, titulo, 1, 0, 'L', 1)
        pdf.set_text_color(0, 0, 150)
        pdf.cell(60, 6, f"Valor por Unidade: {formatar_real(valor_cota_final)}", 1, 1, 'R', 1)
        pdf.set_text_color(0, 0, 0)

        pdf.set_font("Arial", 'B', size=8)
        pdf.cell(190, 5, "COMPOSIÇÃO (Rateio + Fundo + Extras)", 0, 1, 'L')
        pdf.set_font("Arial", size=8)
        pdf.cell(140, 4, f"{int(agua_pct*100)}% Água/Esgoto ({formatar_real(unit_agua)} x {qtd} unid)", "B"); pdf.cell(50, 4, formatar_real(val_agua_total_grupo), "B", 1, 'R')
        if usa_luz_limp:
            pdf.cell(140, 4, f"Luz Condomínio ({formatar_real(unit_luz)} x {qtd} unid)", "B"); pdf.cell(50, 4, formatar_real(val_luz_grupo), "B", 1, 'R')
            pdf.cell(140, 4, f"Limpeza Prédio ({formatar_real(unit_limp)} x {qtd} unid)", "B"); pdf.cell(50, 4, formatar_real(val_limp_grupo), "B", 1, 'R')
        if total_fundo_recebido > 0:
            pdf.cell(140, 4, f"Fundo de Reserva ({formatar_real(unit_fundo)} x {qtd} unid)", "B"); pdf.cell(50, 4, formatar_real(total_fundo_recebido), "B", 1, 'R')
        if not df_extras.empty:
            pdf.ln(1); pdf.set_font("Arial", 'B', size=8); pdf.cell(190, 5, "DESPESAS EXTRAS", 0, 1, 'L'); pdf.set_font("Arial", size=8)
            extras_group = df_extras.groupby("Descrição")["Valor"].sum().reset_index()
            for _, row in extras_group.iterrows():
                nome = re.sub(r"[\[\]']", "", str(row['Descrição'])).replace("Extra: ", "").strip().split("(")[0].strip()
                pdf.cell(140, 4, f"{nome} ({formatar_real(row['Valor']/qtd if qtd>0 else 0)} x {qtd} unid)", "B"); pdf.cell(50, 4, formatar_real(row['Valor']), "B", 1, 'R')
        if not df_ajustes_all.empty:
            pdf.ln(1); pdf.set_font("Arial", 'B', size=8); pdf.cell(190, 5, "AJUSTES / RECUPERAÇÕES", 0, 1, 'L'); pdf.set_font("Arial", size=8)
            for _, row in df_ajustes_all.iterrows():
                if abs(row['Valor']) > 0.01:
                    pdf.cell(140, 4, f"{row['Unidade']}: {row['Descrição']}", "B"); pdf.cell(50, 4, formatar_real(row['Valor']), "B", 1, 'R')
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
                if entradas_uni > (valor_cota_final + 1.00): status_txt = "Pagamento Integral (+ Ajustes)"; cor_texto = (0, 0, 150)
            elif entradas_uni > 0:
                status_txt = f"Parcial (Falta {formatar_real(valor_cota_final - entradas_uni)})"; cor_texto = (200, 100, 0)
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
    
    caminho_final = os.path.join(pasta_destino, nome_arquivo)
    pdf.output(caminho_final)
    return caminho_final

# --- APP PRINCIPAL ---
def main():
    st.sidebar.title("🏢 Edifício San Rafael")
    st.sidebar.divider()
    opcao = st.sidebar.radio("Navegar:", ["Calculadora de Rateio", "Extrato (Dashboard)", "Entradas/Saídas Avulsas", "Cadastros"])
    
    df = carregar_dados()
    df_config = carregar_config()
    
    lista_cats = [x for x in df_config["Categorias"].unique() if x != ""]
    lista_unis = [x for x in df_config["Unidades"].unique() if x != ""]

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
                    st.session_state['extras_editor'] = pd.DataFrame(columns=["Descrição", "Categoria", "Valor Total", "Ratear Para"])
                
                df_extras_input = st.data_editor(
                    st.session_state['extras_editor'],
                    num_rows="dynamic",
                    column_config={
                        "Descrição": st.column_config.TextColumn(required=True, width="medium"),
                        "Categoria": st.column_config.SelectboxColumn(options=lista_cats, required=True, width="medium"),
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
            
            try: ex_sala = df_prev_temp[df_prev_temp['Unidade'].str.contains('Sala')].iloc[0]['Total Devido']
            except: ex_sala = 0
            try: ex_apto = df_prev_temp[df_prev_temp['Unidade'].str.contains('Apto')].iloc[0]['Total Devido']
            except: ex_apto = 0

            res1, res2 = st.columns(2)
            with res1: st.info(f"**SALAS**: Padrão {formatar_real(ex_sala)}")
            with res2: st.success(f"**APARTAMENTOS**: Padrão {formatar_real(ex_apto)}")
            
            st.divider()
            st.subheader("Edição Individual e Pagamento Parcial")

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

            if st.button("🚀 Confirmar e Lançar na Nuvem", type="primary"):
                novos = []
                extras_config_df = d['extras_df'] 

                for i, row in edited_df.iterrows():
                    st_r = row['Status']
                    val_pago = float(row["Valor Pago"])
                    val_devido = float(row["Total Devido"])
                    diferenca = val_pago - val_devido 
                    val_ajuste_individual = float(row["Ajuste"])

                    novos.append({"ID": str(uuid.uuid4()), "Data": d['data'], "Tipo": "Entrada", "Categoria": "Rateio Despesas (Água/Luz)", "Unidade": row['Unidade'], "Descrição": "Rateio", "Valor": row['Rateio'], "Status": st_r})
                    if row['Fundo']>0: novos.append({"ID": str(uuid.uuid4()), "Data": d['data'], "Tipo": "Entrada", "Categoria": "Fundo de Reserva", "Unidade": row['Unidade'], "Descrição": "Fundo", "Valor": row['Fundo'], "Status": st_r})
                    
                    if not extras_config_df.empty:
                        for _, ext_row in extras_config_df.iterrows():
                            val_total = forcar_numero(ext_row.get("Valor Total", 0.0))
                            target = str(ext_row["Ratear Para"])
                            desc_extra = ext_row["Descrição"]
                            cat_extra = ext_row["Categoria"] 
                            aplica = False; div_por = 1
                            if "Todos" in target: aplica = True; div_por = qtd_salas + qtd_aptos
                            elif "Sala" in target and "Sala" in row['Unidade']: aplica = True; div_por = qtd_salas
                            elif "Apto" in target and "Apto" in row['Unidade']: aplica = True; div_por = qtd_aptos
                            if aplica and div_por > 0:
                                val_indiv = val_total / div_por
                                if val_indiv > 0:
                                    novos.append({"ID": str(uuid.uuid4()), "Data": d['data'], "Tipo": "Entrada", "Categoria": cat_extra, "Unidade": row['Unidade'], "Descrição": f"{desc_extra} ({target})", "Valor": val_indiv, "Status": st_r})

                    if val_ajuste_individual != 0:
                        novos.append({"ID": str(uuid.uuid4()), "Data": d['data'], "Tipo": "Entrada", "Categoria": "Ajuste/Gorjeta", "Unidade": row['Unidade'], "Descrição": "Ajuste Manual", "Valor": val_ajuste_individual, "Status": st_r})

                    if diferenca != 0:
                        novos.append({"ID": str(uuid.uuid4()), "Data": d['data'], "Tipo": "Entrada", "Categoria": "Ajuste/Gorjeta", "Unidade": row['Unidade'], "Descrição": "Pendência (Falta)" if diferenca < 0 else "Sobra Pagamento", "Valor": diferenca, "Status": st_r})
                
                if d['totais']['agua']>0: novos.append({"ID": str(uuid.uuid4()), "Data": d['data'], "Tipo": "Saída", "Categoria": "Pagto Água/Esgoto", "Unidade": "Condomínio", "Descrição": "Conta Água", "Valor": d['totais']['agua'], "Status": "Ok"})
                if d['totais']['luz']>0: novos.append({"ID": str(uuid.uuid4()), "Data": d['data'], "Tipo": "Saída", "Categoria": "Pagto Luz", "Unidade": "Condomínio", "Descrição": "Conta Luz", "Valor": d['totais']['luz'], "Status": "Ok"})
                if d['totais']['limp']>0: novos.append({"ID": str(uuid.uuid4()), "Data": d['data'], "Tipo": "Saída", "Categoria": "Pagto Limpeza", "Unidade": "Condomínio", "Descrição": "Limpeza", "Valor": d['totais']['limp'], "Status": "Ok"})
                
                salvar_dados(pd.concat([df, pd.DataFrame(novos)], ignore_index=True))
                
                del st.session_state['dados_rateio']
                del st.session_state['df_preview']
                st.rerun()

    elif opcao == "Extrato (Dashboard)":
        st.header("📊 Dashboard - Edifício San Rafael")
        if df.empty:
            st.warning("⚠️ Nenhum dado encontrado na Planilha."); st.stop()

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
        
        # --- PAINEL DE INADIMPLÊNCIA ---
        st.divider()
        st.subheader("🚨 Controle de Inadimplência")
        
        mask_divida_pura = (df["Tipo"] == "Entrada") & (df["Valor"] < -0.01)
        mask_recuperacao = (df["Tipo"] == "Entrada") & (df["Valor"] > 0) & (df["Categoria"].str.contains("Ajuste", case=False, na=False))
        df_ajustes_global = df[mask_divida_pura | mask_recuperacao]
        
        devedores_list = []
        if not df_ajustes_global.empty:
            saldo_por_unidade = df_ajustes_global.groupby("Unidade")["Valor"].sum().reset_index()
            devedores = saldo_por_unidade[saldo_por_unidade["Valor"] < -0.05] 
            
            if not devedores.empty:
                st.error(f"Total Pendente: {formatar_real(devedores['Valor'].sum())}")
                
                devedores_show = devedores.rename(columns={"Valor": "Saldo Devedor"}).copy()
                devedores_show["Saldo Devedor"] = devedores_show["Saldo Devedor"].apply(formatar_real)
                st.dataframe(devedores_show, use_container_width=True)
                devedores_list = devedores["Unidade"].tolist()
                
                # BAIXA RÁPIDA
                st.write("---")
                st.write("💰 **Baixa Rápida de Pendências**")
                c_pay1, c_pay2, c_pay3 = st.columns([2, 1, 1])
                uni_pag = c_pay1.selectbox("Selecione a Unidade para Baixar", devedores_list)
                dt_pagamento = c_pay2.date_input("Data do Pagamento", datetime.today())
                valor_divida_atual = 0.0
                if uni_pag:
                    val_calc = devedores[devedores["Unidade"]==uni_pag]["Valor"].values
                    if len(val_calc) > 0: valor_divida_atual = abs(val_calc[0])
                valor_pag = c_pay3.number_input("Valor Recebido (R$)", min_value=0.0, value=valor_divida_atual, format="%.2f")
                
                if st.button("Registrar Pagamento da Dívida", type="primary"):
                    novo_pagamento = {
                        "ID": str(uuid.uuid4()), "Data": dt_pagamento, "Tipo": "Entrada", "Categoria": "Ajuste/Gorjeta", "Unidade": uni_pag, "Descrição": f"Recuperação de Atrasados - {uni_pag}", "Valor": valor_pag, "Status": "Ok"
                    }
                    df_final = pd.concat([df, pd.DataFrame([novo_pagamento])], ignore_index=True)
                    salvar_dados(df_final)
                    st.rerun()
            else:
                st.success("Nenhuma pendência financeira encontrada.")
        else:
            st.success("Nenhuma pendência registrada.")

        st.divider()
        st.subheader("Detalhamento e Edição")
        
        # Correção do Index para st.data_editor
        df_ver_reset = df_ver.reset_index(drop=True)
        
        df_editado = st.data_editor(
            df_ver_reset, hide_index=True, width="stretch", num_rows="dynamic",
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

        if st.button("💾 Salvar Alterações na Nuvem", type="primary"):
            df_orig = carregar_dados()
            
            df_editado["ID"] = df_ver_reset["ID"]
            for i, row in df_editado.iterrows():
                if pd.isna(row["ID"]) or row["ID"] == "": df_editado.at[i, "ID"] = str(uuid.uuid4())
            
            ids_visualizados = df_ver_reset["ID"].tolist()
            ids_finais = df_editado["ID"].tolist()
            ids_para_excluir = set(ids_visualizados) - set(ids_finais)
            
            if ids_para_excluir: 
                df_orig = df_orig[~df_orig["ID"].isin(ids_para_excluir)]
            
            ids_editados = df_editado["ID"].tolist()
            df_orig = df_orig[~df_orig["ID"].isin(ids_editados)]
            
            df_final = pd.concat([df_orig, df_editado], ignore_index=True)
            salvar_dados(df_final)
            st.rerun()

        st.divider()
        e_per = df_ver["Valor"][df_ver["Tipo"]=="Entrada"].sum()
        s_per = df_ver["Valor"][df_ver["Tipo"]=="Saída"].sum()
        
        mask_acum = [True] * len(df)
        if ano != "Todos":
            if mes_key != 13: mask_acum = (df["Data"].dt.year < ano) | ((df["Data"].dt.year == ano) & (df["Data"].dt.month <= mes_key))
            else: mask_acum = (df["Data"].dt.year <= ano)
        df_acum = df[mask_acum]
        ent_total = df_acum[df_acum["Tipo"]=="Entrada"]["Valor"].sum()
        sai_total = df_acum[df_acum["Tipo"]=="Saída"]["Valor"].sum()
        
        df_extras_dash = df_acum[_mask_extras_rateio(df_acum)]
        val_extras_dash = df_extras_dash["Valor"].sum()
        saldo_acumulado = ent_total - val_extras_dash - sai_total

        df_extras_per = df_ver[_mask_extras_rateio(df_ver)]
        val_extras_per = df_extras_per["Valor"].sum()
        delta_val = e_per - s_per - val_extras_per

        c1, c2, c3 = st.columns(3)
        c1.metric("Entradas (Período)", formatar_real(e_per))
        c2.metric("Saídas (Período)", formatar_real(s_per))
        c3.metric("Saldo em Caixa (Acumulado)", formatar_real(saldo_acumulado), delta=f"Res. Período: {formatar_real(delta_val)}")

        if st.button("📄 Gerar Relatório (PDF)", type="primary"):
            nome_mes = list(meses.keys())[list(meses.values()).index(meses[mes_key])]
            arq = gerar_relatorio_prestacao(df, mes_key, nome_mes, ano, lista_unis)
            with open(arq, "rb") as f:
                st.download_button("Baixar PDF Agora", f, file_name=os.path.basename(arq), type="primary")

    elif opcao == "Entradas/Saídas Avulsas":
        st.header("💸 Lançamentos Avulsos")
        t1, t2 = st.tabs(["Lançamento Avulso", "Definir Saldo Inicial"])
        with t1:
            with st.form("av"):
                dt = st.date_input("Data", datetime.today())
                tp = st.selectbox("Tipo", ["Saída", "Entrada"])
                ct = st.selectbox("Categoria", lista_cats)
                un = st.selectbox("Unidade / Centro de Custo", ["Condomínio (Geral)"] + lista_unis)
                vl = st.number_input("Valor", min_value=0.0, format="%.2f")
                ds = st.text_input("Descrição")
                if st.form_submit_button("Salvar na Nuvem", type="primary"):
                    novo_dado = pd.DataFrame([{"ID":str(uuid.uuid4()), "Data":dt, "Tipo":tp, "Categoria":ct, "Unidade":un, "Descrição":ds, "Valor":vl, "Status":"Ok"}])
                    salvar_dados(pd.concat([df, novo_dado], ignore_index=True))
        with t2:
            st.info("Define o saldo inicial histórico (antes de 2020).")
            with st.form("si"):
                dt = st.date_input("Data do Saldo Inicial", datetime(2020, 1, 1))
                vl = st.number_input("Valor Inicial (R$)", min_value=0.0, format="%.2f")
                if st.form_submit_button("Registrar Saldo", type="primary"):
                    novo_dado = pd.DataFrame([{"ID":str(uuid.uuid4()), "Data":dt, "Tipo":"Entrada", "Categoria":"Saldo Inicial", "Unidade":"Caixa", "Descrição":"Saldo Inicial", "Valor":vl, "Status":"Ok"}])
                    salvar_dados(pd.concat([df, novo_dado], ignore_index=True))

    elif opcao == "Cadastros":
        st.header("⚙️ Configurações")
        c1, c2 = st.columns(2)
        d_c = c1.data_editor(pd.DataFrame({"Categoria":lista_cats}), num_rows="dynamic", width="stretch", key="ed_cats")
        d_u = c2.data_editor(pd.DataFrame({"Unidade":lista_unis}), num_rows="dynamic", width="stretch", key="ed_unis")
        if st.button("Salvar Configurações", type="primary"):
            cats = d_c["Categoria"].tolist(); unis = d_u["Unidade"].tolist()
            max_len = max(len(cats), len(unis))
            cats += [""] * (max_len - len(cats)); unis += [""] * (max_len - len(unis))
            salvar_config(pd.DataFrame({"Categorias": cats, "Unidades": unis}))
            st.rerun()

if __name__ == "__main__":
    main()
