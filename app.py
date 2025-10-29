import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import requests

# --- APIキー・認証設定 ---
API_ENDPOINT = "https://app.rakuten.co.jp/services/api/BooksBook/Search/20170404"

# シークレット設定の確認とエラーハンドリング
try:
    API_KEY = st.secrets["rakuten"]["applicationId"]
    AFFILIATE_ID = st.secrets["rakuten"]["affiliateId"]
except KeyError as e:
    st.error(f"設定エラー: 楽天APIキーが見つかりません。管理者に連絡してください。\nエラー詳細: {e}")
    st.stop()
except Exception as e:
    st.error(f"予期しないエラーが発生しました: {e}")
    st.stop()


# --- Google Sheets認証 ---
def get_gspread_client():
    try:
        creds = Credentials.from_service_account_info(
            st.secrets["gcp_service_account"],
            scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
        )
        return gspread.authorize(creds)
    except KeyError as e:
        st.error(f"設定エラー: Google Cloud認証情報が見つかりません。管理者に連絡してください。\nエラー詳細: {e}")
        st.stop()
    except Exception as e:
        st.error(f"Google Sheets認証でエラーが発生しました: {e}")
        st.stop()


# --- 楽天Books API ---
def get_books(params, search_title, num, no):
    params["page"] = 1
    response = requests.get(API_ENDPOINT, params=params)
    if response.status_code != 200:
        st.error(f"エラー: {response.status_code} (page=1)")
        return no

    data = response.json()
    page_count = data.get("pageCount", 1)
    books = data.get("Items", [])

    if page_count >= 1:
        num = int(num) + 1
        search_title = search_title.replace("num", str(num))
        for book_item in books:
            book = book_item["Item"]
            if search_title in book["title"]:
                no += 1
                st.write(f'{no} : {book["title"]} | ISBN: {book["isbn"]} | 出版日: {book["salesDate"]}')
                return no
    return no


# --- メイン ---
def main():
    st.title("📚 楽天Books 最新巻チェック")

    # デバッグ情報（開発時のみ表示）
    if st.checkbox("設定情報を表示（デバッグ用）"):
        st.write("**設定状況:**")
        st.write(f"- 楽天API Key: {'✅ 設定済み' if 'API_KEY' in globals() else '❌ 未設定'}")
        st.write(f"- 楽天Affiliate ID: {'✅ 設定済み' if 'AFFILIATE_ID' in globals() else '❌ 未設定'}")
        st.write(f"- Google Cloud認証: {'✅ 設定済み' if 'gcp_service_account' in st.secrets else '❌ 未設定'}")

    if st.button("最新刊チェック開始 ▶️"):
        st.info("Googleスプレッドシートを取得中...")

        gc = get_gspread_client()
        spreadsheet = gc.open("作品一覧")
        worksheet = spreadsheet.get_worksheet(0)

        rows = worksheet.get_all_values()
        st.success(f"{len(rows)-1}件の作品データを取得しました。")

        data = []
        for row in rows[1:]:
            title = row[0] if len(row) > 0 else ""
            search_title = row[1] if len(row) > 1 else ""
            number = row[2] if len(row) > 2 else ""
            data.append({"title": title, "search_title": search_title, "number": number})

        no = 0
        st.subheader("🔎 検索結果")
        for item in data:
            params = {
                'applicationId': API_KEY,
                'affiliateId': AFFILIATE_ID,
                'title': item["title"],
                'sort': '-releaseDate',
                'hits': 30
            }
            result = get_books(params, item["search_title"], item["number"], int(no))
            no = int(result)

        st.success("✅ 最新刊チェックが完了しました！")


if __name__ == "__main__":
    main()
