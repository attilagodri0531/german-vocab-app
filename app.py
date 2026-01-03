import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
from openai import OpenAI
from dotenv import load_dotenv
import time

# --- PAGE SETUP ---
st.set_page_config(page_title="German Hustler AI (V5)", page_icon="⚡")

# --- SETUP & LOGIC ---
load_dotenv() # Load local .env file first (safest for local)

# Initialize API Key
api_key = None

# 1. Try loading from Streamlit Secrets (Best for Cloud)
try:
    if "OPENAI_API_KEY" in st.secrets:
        api_key = st.secrets["OPENAI_API_KEY"]
except Exception:
    # If secrets file is missing (Local execution), ignore and pass
    pass

# 2. If not found in Secrets, try Local Environment (Best for Laptop)
if not api_key:
    api_key = os.getenv("OPENAI_API_KEY")

# 3. Final Check
if not api_key:
    st.error("❌ API Key missing! Check .env (Local) or Secrets (Cloud).")
    st.stop()

client = OpenAI(api_key=api_key)

# Connect to Google Sheets
SCOPE = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
SHEET_NAME = "german_vocab_db" 

def get_google_sheet():
    try:
        if "gcp_service_account" in st.secrets:
            key_dict = dict(st.secrets["gcp_service_account"])
            creds = ServiceAccountCredentials.from_json_keyfile_dict(key_dict, SCOPE)
        elif os.path.exists("service_account.json"):
            creds = ServiceAccountCredentials.from_json_keyfile_name("service_account.json", SCOPE)
        else:
            st.error("❌ No credentials found!")
            st.stop()
        gc = gspread.authorize(creds)
        return gc.open(SHEET_NAME).sheet1
    except Exception as e:
        st.error(f"❌ Connection Error: {e}")
        st.stop()

def load_data():
    sheet = get_google_sheet()
    data = sheet.get_all_records()
    if not data:
        return pd.DataFrame(columns=["Article", "Word", "Plural", "Hungarian", "Sentence_DE", "Sentence_HU"])
    return pd.DataFrame(data)

def save_new_word(data_list):
    sheet = get_google_sheet()
    if len(sheet.get_all_values()) == 0:
        headers = ["Article", "Word", "Plural", "Hungarian", "Sentence_DE", "Sentence_HU"]
        sheet.append_row(headers)
    sheet.append_row(data_list)
    return True

# --- AI LOGIC (No changes here) ---
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
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": f"Input: '{user_input}'"}
            ],
            temperature=0
        )
        raw_answer = response.choices[0].message.content.strip()
        
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
        
        article = parts[0].lower()
        word = parts[1]
        if word.lower().startswith(article + " ") and article in ["der", "die", "das"]:
            parts[1] = word[len(article):].strip()
        return parts
    except Exception:
        return None

# --- UI SECTION ---
st.title("⚡ German Hustler V5 (Bulk Mode)")
st.write("Add multiple words separated by **commas** (e.g., `Hund, Katze, Maus`).")

# 1. BULK INPUT FORM
with st.form("bulk_form", clear_on_submit=True):
    # Changed from text_input to text_area
    raw_text = st.text_area("Enter words:", height=100)
    submitted = st.form_submit_button("🚀 Analyze All")

    if submitted and raw_text:
        # Split by comma or newlines to get a list
        word_list = [w.strip() for w in raw_text.replace('\n', ',').split(',') if w.strip()]
        
        if not word_list:
            st.warning("Please enter at least one word.")
        else:
            # Progress Bar Setup
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            df = load_data()
            existing_words = []
            if not df.empty:
                existing_words = df["Word"].astype(str).str.lower().values
            
            success_count = 0
            
            for i, word in enumerate(word_list):
                # Update status
                status_text.text(f"🤖 Processing: '{word}'...")
                
                # Check duplicate (Basic check before AI)
                if word.lower() in existing_words:
                    st.toast(f"⚠️ Skipped '{word}' (Already exists)", icon="⏭️")
                else:
                    # Run AI
                    details = get_word_details(word)
                    if details:
                        # Double check duplicate after lemmatization (e.g. "Hunde" -> "Hund")
                        clean_word = details[1]
                        if clean_word.lower() in existing_words:
                            st.toast(f"⚠️ Skipped '{word}' -> '{clean_word}' (Exists)", icon="⏭️")
                        else:
                            save_new_word(details)
                            st.toast(f"✅ Added: {clean_word}", icon="🎉")
                            success_count += 1
                            # Add to local list to prevent duplicates within the same batch
                            existing_words = list(existing_words)
                            existing_words.append(clean_word.lower())
                    else:
                        st.toast(f"❌ '{word}' invalid.", icon="🚫")
                
                # Update bar
                progress_bar.progress((i + 1) / len(word_list))
            
            status_text.text("Done!")
            time.sleep(1)
            status_text.empty()
            progress_bar.empty()
            
            if success_count > 0:
                st.success(f"✨ Successfully added {success_count} new words!")
            else:
                st.warning("No new words were added.")

# 2. ANKI EXPORT SECTION
st.divider()
st.subheader("📚 Database & Anki Export")

try:
    df = load_data()
    if not df.empty:
        # Show editable table
        st.data_editor(df, key="editor", num_rows="dynamic", use_container_width=True)
        
        # --- ANKI CSV GENERATOR ---
        # We create a new valid CSV for Anki: Front (Question) | Back (Answer)
        # Front: Article + Word
        # Back: Translation + Plural + Sentence
        
        anki_df = pd.DataFrame()
        # Combine Article and Word for the "Front" of the card
        anki_df['Front'] = df.apply(lambda x: f"{x['Article']} {x['Word']}" if x['Article'] != '-' else x['Word'], axis=1)
        
        # Combine everything else for the "Back"
        anki_df['Back'] = df.apply(lambda x: f"{x['Hungarian']}<br><br>Plural: {x['Plural']}<br>🇩🇪 {x['Sentence_DE']}<br>🇭🇺 {x['Sentence_HU']}", axis=1)
        
        # Convert to CSV
        csv = anki_df.to_csv(index=False, header=False, sep=';') # Semicolon is safer for Anki
        
        st.download_button(
            label="📥 Download Anki Deck (.csv)",
            data=csv,
            file_name="german_anki_deck.csv",
            mime="text/csv",
        )
        st.caption("Import this into Anki. Use 'Semicolon' as separator. Allow HTML.")
        
    else:
        st.info("Database empty.")

except Exception as e:
    st.error(f"Error loading data: {e}")

