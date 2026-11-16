import streamlit as st
import pandas as pd
import io
import zipfile
import re

# --- CONFIGURAZIONE PAROLE CHIAVE PER CATEGORIE ---
# Puoi aggiungere tutti i brand o generi che vuoi in queste liste (tutto in minuscolo)
GENDERS_TO_EXTRACT = ["uomo", "donna", "bambino", "bambina", "ragazzo", "ragazza", "unisex"]
BRANDS_TO_EXTRACT = ["hugo boss", "cavalli", "armani", "gucci", "prada", "guess", "calvin klein", "tommy hilfiger", "michael kors", "versace"]

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="Convertitore Woo + Pacchetti", page_icon="📦", layout="wide")

st.title("📦 Convertitore StockFirmati -> WooCommerce (V8 + Auto-Categorie)")
st.markdown("""
- **Prezzi e IVA** configurabili per categoria.
- **Suddivisione intelligente in pacchetti ZIP** (non separa mai i padri dai figli).
- **Auto-Mappatura in inglese** per evitare errori in WooCommerce.
- **Estrazione Categorie Automatica:** Aggiunge Genere e Brand se presenti in descrizione.
""")

# --- CARICAMENTO FILE ---
uploaded_file = st.file_uploader("Trascina qui il file originale (con le | o le virgole)", type=['csv', 'txt'])

if uploaded_file is not None:
    try:
        # Lettura del file
        try:
            df = pd.read_csv(uploaded_file, sep='|', quotechar='"', dtype=str, encoding='utf-8', on_bad_lines='skip')
        except:
            uploaded_file.seek(0)
            df = pd.read_csv(uploaded_file, sep=',', dtype=str, encoding='utf-8', on_bad_lines='skip')
            
        df = df.fillna('')
        df.columns = df.columns.str.strip()
        
    except Exception as e:
        st.error(f"Errore nella lettura del file: {e}")
        st.stop()

    st.divider()
    
    # --- PANNELLO CONFIGURAZIONE ---
    st.subheader("🛠️ 1. Configurazione Prezzi e Suddivisione")
    
    col1, col2 = st.columns([1, 1])
    with col1:
        max_rows_per_file = st.number_input("Righe massime per pacchetto (circa)", min_value=100, max_value=5000, value=1000, step=100)
        st.caption("Il taglio avverrà sempre tra un prodotto e l'altro, mai spezzando le varianti.")
    with col2:
        vat_percent = st.number_input("IVA % (da aggiungere dopo il ricarico)", value=22.0, step=1.0)
    
    st.write("---")
    st.write("**Ricarico % per Categoria:**")
    
    # Estrai categorie uniche
    unique_cats = sorted([x for x in df.get('CAT', pd.Series()).unique() if str(x).strip() != ''])
    user_markups = {}
    
    if unique_cats:
        cols = st.columns(3)
        for idx, cat_name in enumerate(unique_cats):
            # Default 40% per abbigliamento, 20% altrimenti
            default_markup = 40.0 if 'abbigliamento' in str(cat_name).lower() else 20.0
            with cols[idx % 3]:
                user_markups[cat_name] = st.number_input(f"Ricarico '{cat_name}'", value=default_markup, step=5.0, key=f"mk_{idx}")
    else:
        st.warning("Nessuna categoria trovata nel file per impostare i ricarichi specifici.")

    st.divider()
    
    # --- PULSANTE DI AVVIO ---
    if st.button("🚀 GENERA PACCHETTI ZIP", type="primary"):
        st.info("Elaborazione in corso, attendere...")
        
        # Nomi colonne in inglese per auto-mappatura WooCommerce
        output_columns = [
            'Type', 'SKU', 'Name', 'Published', 'Visibility in catalog', 
            'Description', 'In stock?', 'Stock', 'Manage stock?', 'Regular price', 
            'Categories', 'Shipping class', 'Images', 'Parent', 
            'Attribute 1 name', 'Attribute 1 value(s)', 'Attribute 1 visible', 'Attribute 1 global', 
            'Attribute 2 name', 'Attribute 2 value(s)', 'Attribute 2 visible', 'Attribute 2 global', 
            'Attribute 3 name', 'Attribute 3 value(s)', 'Attribute 3 visible', 'Attribute 3 global'
        ]
        
        if 'SKU' not in df.columns:
            st.error("Colonna SKU mancante nel file originale.")
            st.stop()
            
        grouped = df.groupby('SKU')
        total_groups = len(grouped)
        bar = st.progress(0)
        
        chunks = []
        current_chunk = []
        current_row_count = 0
        
        # ELABORAZIONE
        for i, (sku, group) in enumerate(grouped):
            family_rows = []
            
            parent_row = group[(group['RECORD_TYPE'].str.upper() == 'PRODUCT') | (group['RECORD_TYPE'].str.lower() == 'variable')]
            children_rows = group[(group['RECORD_TYPE'].str.upper() == 'MODEL') | (group['RECORD_TYPE'].str.lower() == 'variation')]
            
            if parent_row.empty:
                continue
                
            parent = parent_row.iloc[0]
            
            # Preparazione dati padre
            parent_sku = parent.get('ORDERCODE', '').strip() or parent.get('SKU', '').strip()
            cat_raw = parent.get('CAT', '').strip()
            cat_final = f"{cat_raw} Stock" if cat_raw and not cat_raw.lower().endswith('stock') else cat_raw
            
            # ---> NUOVA LOGICA: ESTRAZIONE GENERE E BRAND <---
            titel_str = str(parent.get('Titel_ITA', ''))
            desc_str = str(parent.get('Description_ITA', ''))
            text_to_search = f"{titel_str} {desc_str}".lower()
            
            extra_cats = []
            
            # Cerca generi
            for g in GENDERS_TO_EXTRACT:
                if re.search(r'\b' + re.escape(g) + r'\b', text_to_search):
                    extra_cats.append(g.capitalize())
                    
            # Cerca brand
            for b in BRANDS_TO_EXTRACT:
                if re.search(r'\b' + re.escape(b) + r'\b', text_to_search):
                    extra_cats.append(b.title()) # .title() trasforma 'hugo boss' in 'Hugo Boss'
            
            # Unisci la categoria base con le nuove trovate, rimuovendo duplicati e vuoti
            cat_list = [cat_final] + extra_cats
            cat_final_string = ", ".join(sorted(list(set([c for c in cat_list if c]))))
            # ---------------------------------------------------

            imgs = [parent.get('PICTURE_1', ''), parent.get('PICTURE_2', ''), parent.get('PICTURE_3', '')]
            imgs_str = ', '.join([x for x in imgs if x])
            
            sizes = sorted(list(set([x for x in children_rows['MODEL_SIZE'].unique() if x])))
            colors = sorted(list(set([x for x in children_rows['COLOR'].unique() if x])))
            sexes = sorted(list(set([x for x in children_rows['SEX'].unique() if x])))
            
            # RIGA PADRE
            p_out = {col: '' for col in output_columns}
            p_out.update({
                'Type': 'variable', 'SKU': parent_sku, 'Name': titel_str,
                'Published': '1', 'Visibility in catalog': 'visible', 'Description': desc_str,
                'In stock?': '1', 'Manage stock?': '0', 'Images': imgs_str, 
                'Categories': cat_final_string, # Inseriamo la nuova stringa con le categorie extra
                'Shipping class': 'stock-firmati',
                'Attribute 1 name': 'Taglia', 'Attribute 1 value(s)': ', '.join(sizes), 'Attribute 1 visible': '1', 'Attribute 1 global': '1',
                'Attribute 2 name': 'Colore', 'Attribute 2 value(s)': ', '.join(colors), 'Attribute 2 visible': '1', 'Attribute 2 global': '1',
                'Attribute 3 name': 'Genere', 'Attribute 3 value(s)': ', '.join(sexes), 'Attribute 3 visible': '1', 'Attribute 3 global': '1'
            })
            family_rows.append(p_out)
            
            # RIGHE FIGLI
            for _, child in children_rows.iterrows():
                c_out = {col: '' for col in output_columns}
                
                # Calcolo prezzo con Ricarico e IVA
                try:
                    base_price = float(str(child.get('PRICE', '0')).replace(',', '.'))
                    markup_perc = user_markups.get(cat_raw, 20.0)
                    price_with_markup = base_price * (1 + markup_perc / 100)
                    final_price = price_with_markup * (1 + vat_percent / 100)
                    final_price_str = "{:.2f}".format(final_price)
                except ValueError:
                    final_price_str = ""
                
                child_sku = child.get('ORDERCODE', '').strip() or child.get('SKU', '').strip()
                qty = str(child.get('QUANTITY', '0')).strip() or '0'
                
                c_out.update({
                    'Type': 'variation', 'SKU': child_sku, 'Name': f"{titel_str} - {child.get('MODEL_SIZE', '')}",
                    'Published': '1', 'Visibility in catalog': 'visible', 'Parent': parent_sku,
                    'In stock?': '1', 'Stock': qty, 'Manage stock?': '1', 'Regular price': final_price_str,
                    'Shipping class': 'stock-firmati',
                    'Attribute 1 name': 'Taglia', 'Attribute 1 value(s)': child.get('MODEL_SIZE', ''), 'Attribute 1 global': '1',
                    'Attribute 2 name': 'Colore', 'Attribute 2 value(s)': child.get('COLOR', ''), 'Attribute 2 global': '1',
                    'Attribute 3 name': 'Genere', 'Attribute 3 value(s)': child.get('SEX', ''), 'Attribute 3 global': '1'
                })
                family_rows.append(c_out)
            
            # Aggiungi famiglia al pacchetto corrente
            current_chunk.extend(family_rows)
            current_row_count += len(family_rows)
            
            # Taglio pacchetto se supera la soglia specificata
            if current_row_count >= max_rows_per_file:
                chunks.append(current_chunk)
                current_chunk = []
                current_row_count = 0
            
            if i % 10 == 0:
                bar.progress(min(i / total_groups, 1.0))
        
        # Aggiungi residuo all'ultimo pacchetto
        if current_chunk:
            chunks.append(current_chunk)
            
        bar.progress(1.0)
        
        # --- CREAZIONE FILE ZIP ---
        st.success(f"✅ Finito! Creati {len(chunks)} pacchetti pronti per l'importazione.")
        
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for idx, chunk in enumerate(chunks):
                df_chunk = pd.DataFrame(chunk)
                csv_string = df_chunk.to_csv(index=False)
                zip_file.writestr(f"import_parte_{idx+1}.csv", csv_string)
        
        zip_buffer.seek(0)
        
        st.download_button(
            label="⬇️ SCARICA ARCHIVIO ZIP CON I FILE DIVISI",
            data=zip_buffer,
            file_name='pacchetti_woocommerce.zip',
            mime='application/zip',
        )
