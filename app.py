import streamlit as st
import pandas as pd
import requests
import io
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# --- タイトル ---
st.title("📚 漫画最新刊チェックアプリ")

# --- Drive API認証 ---
scopes = ["https://www.googleapis.com/auth/drive.readonly"]
creds = Credentials.from_service_account_info(
    st.secrets["gcp_service_account"], scopes=scopes
)
drive_service = build("drive", "v3", credentials=creds)

# --- 対象ファイルID（GoogleドライブURLの d/○○/ 部分） ---
FILE_ID = "ここにファイルIDを入力"

# --- ファイル取得 ---
@st.cache_data
def load_excel_from_drive(file_id):
    request = drive_service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
    fh.seek(0)
    return pd.read_excel(fh)

df = load_excel_from_drive(FILE_ID)
st.write("### 📋 現在のスプレッドシート内容")
st.dataframe(df)

# --- 楽天Books API ---
API_ENDPOINT = "https://app.rakuten.co.jp/services/api/BooksBook/Search/20170404"
API_KEY = st.secrets["rakuten"]["API_KEY"]

if st.button("🔍 最新刊をチェック"):
    updated_list = []
    for _, row in df.iterrows():
        title = row.get("タイトル") or row.get("作品名")
        if not title:
            continue

        params = {
            "applicationId": API_KEY,
            "title": title,
            "hits": 1,
            "sort": "-releaseDate",
        }
        res = requests.get(API_ENDPOINT, params=params)
        items = res.json().get("Items", [])

        if items:
            latest_title = items[0]["Item"]["title"]
            if latest_title != title:
                updated_list.append({"旧タイトル": title, "新タイトル": latest_title})

    if updated_list:
        st.warning("📗 新刊が出ている作品：")
        st.dataframe(pd.DataFrame(updated_list))
    else:
        st.success("すべて最新です！")
