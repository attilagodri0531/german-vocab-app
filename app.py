import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
from openai import OpenAI
from dotenv import load_dotenv

# --- PAGE SETUP ---
st.set_page_config(page_title="German Hustler AI (Cloud)", page_icon="☁️")

# --- SETUP & LOGIC ---
load_dotenv()

# 1. API Key Setup
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    st.error("❌ API Key missing! Check your .env file.")
    st.stop()

client = OpenAI(api_key=api_key)

# 2. Google Sheets Connection (The New Database)
SCOPE = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
SHEET_NAME = "german_vocab_db" # Make sure this matches your Sheet name EXACTLY

def get_google_sheet():
    """Connects to Google Sheets using Streamlit Secrets (Cloud) or Local JSON (Laptop)"""
    try:
        # 1. Try Streamlit Cloud Secrets first (The Pro Way)
        if "gcp_service_account" in st.secrets:
            # We create a dictionary from the secrets
            key_dict = dict(st.secrets["gcp_service_account"])
            # Load credentials from that dictionary
            creds = ServiceAccountCredentials.from_json_keyfile_dict(key_dict, SCOPE)
            
        # 2. Fallback to local JSON file (For your laptop)
        elif os.path.exists("service_account.json"):
            creds = ServiceAccountCredentials.from_json_keyfile_name("service_account.json", SCOPE)
            
        else:
            st.error("❌ No credentials found! Check Streamlit Secrets or local JSON file.")
            st.stop()
            
        gc = gspread.authorize(creds)
        return gc.open(SHEET_NAME).sheet1
        
    except Exception as e:
        st.error(f"❌ Connection Error: {e}")
        st.stop()

def load_data():
    """Reads data from Google Cloud"""
    sheet = get_google_sheet()
    data = sheet.get_all_records()
    
    if not data:
        # If sheet is empty, return empty DF with columns
        return pd.DataFrame(columns=["Article", "Word", "Plural", "Hungarian", "Sentence_DE", "Sentence_HU"])
        
    return pd.DataFrame(data)

def save_new_word(data_list):
    """Appends a new row to Google Cloud"""
    sheet = get_google_sheet()
    # Check if headers exist, if not add them
    if len(sheet.get_all_values()) == 0:
        headers = ["Article", "Word", "Plural", "Hungarian", "Sentence_DE", "Sentence_HU"]
        sheet.append_row(headers)
        
    sheet.append_row(data_list)
    return True

def update_entire_sheet(df):
    """Overwrites the Cloud Sheet with edits"""
    sheet = get_google_sheet()
    sheet.clear() # Wipe old data
    # GSpread expects a list of lists, including headers
    val_list = [df.columns.values.tolist()] + df.values.tolist()
    sheet.update(val_list)

# --- AI LOGIC (Same as before) ---
def get_word_details(user_input):
    system_instruction = """
    You are a German Dictionary Database.
    TASK: Convert User Input to Dictionary Root (Lemma).
    RULES:
    1. NOUNS: Return Singular Nominative + Article (der/die/das).
    2. VERBS: Return Infinitive. Article is '-'.
    3. ADJECTIVES: Positive form. Article is '-'.
    4. GIBBERISH: Return "INVALID"
    OUTPUT FORMAT (Data Only, NO Header):
    Article | Word | Plural | Hungarian | German Sentence | Hungarian Sentence
    """
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": f"Input: '{user_input}'"}
        ],
        temperature=0
    )
    raw_answer = response.choices[0].message.content.strip()
    
    # Parsing Logic
    lines = raw_answer.split('\n')
    final_data_line = ""
    for line in lines:
        if "Article | Word" in line: continue
        if line.strip(): 
            final_data_line = line.strip()
            break
            
    if "INVALID" in final_data_line.upper(): return None

    if " | " in final_data_line: parts = final_data_line.split(" | ")
    else: parts = final_data_line.split("|")
    
    parts = [p.strip() for p in parts]
    if len(parts) == 5: parts.append("")
    
    # Clean Article from Word
    article = parts[0].lower()
    word = parts[1]
    if word.lower().startswith(article + " ") and article in ["der", "die", "das"]:
        parts[1] = word[len(article):].strip()
    return parts

# --- UI SECTION ---
st.title("🇩🇪 German Vocab Builder (Cloud ☁️)")
st.write("Data lives in Google Sheets. Access from anywhere.")

with st.form("vocab_form", clear_on_submit=True):
    user_input = st.text_input("Enter a German word:")
    submitted = st.form_submit_button("Analyze & Add")

    if submitted and user_input:
        with st.spinner(f"🤖 Analyzing '{user_input}'..."):
            try:
                df = load_data()
                # Check duplicates locally first
                if not df.empty and user_input.lower() in df["Word"].astype(str).str.lower().values:
                     st.warning(f"⚠️ '{user_input}' might already be in the list.")

                details = get_word_details(user_input)
                
                if details:
                    corrected_word = details[1]
                    # Check duplicates again with corrected word
                    if not df.empty and corrected_word.lower() in df["Word"].astype(str).str.lower().values:
                        st.error(f"🛑 '{corrected_word}' is already in the database.")
                    else:
                        save_new_word(details)
                        st.success(f"✅ Saved to Cloud: **{details[0]} {details[1]}**")
                        st.info(f"🗣️ {details[4]}")
                else:
                    st.error("❌ Not a valid word.")
            except Exception as e:
                st.error(f"Error: {e}")

# --- EDITABLE TABLE ---
st.divider()
st.subheader("📚 Live Cloud Database")

try:
    df = load_data()
    if not df.empty:
        edited_df = st.data_editor(
            df, 
            num_rows="dynamic", 
            use_container_width=True,
            key="editor"
        )

        if st.button("💾 Save Edits to Google Cloud"):
            with st.spinner("Syncing to Google..."):
                update_entire_sheet(edited_df)
                st.success("✅ Google Sheet Updated!")
                st.rerun()
    else:
        st.info("Database is empty. Add a word!")

except Exception as e:

    st.error(f"Could not load data. Check JSON key or Sheet name. Error: {e}")
