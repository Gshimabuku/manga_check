import streamlit as st
import gspread
# gspread moved exception classes into gspread.exceptions in newer versions.
# Use a compatibility import so the app works with different gspread versions.
try:
    from gspread.exceptions import SpreadsheetNotFound, APIError
except Exception:
    # Fallback for older gspread versions that exported these at top-level
    from gspread import SpreadsheetNotFound, APIError
from google.oauth2.service_account import Credentials
import requests
import os

# --- APIキー・認証設定 ---
API_ENDPOINT = "https://app.rakuten.co.jp/services/api/BooksBook/Search/20170404"
SPREADSHEET_NAME = "作品一覧"  # 固定のスプレッドシート名

# シークレット設定の確認とエラーハンドリング
def get_api_keys():
    """APIキーを複数の方法で取得を試みる"""
    api_key = None
    affiliate_id = None
    
    # 方法1: Streamlit secrets
    try:
        api_key = st.secrets["rakuten"]["applicationId"]
        affiliate_id = st.secrets["rakuten"]["affiliateId"]
        st.success("✅ Streamlit secretsから設定を読み込みました")
        return api_key, affiliate_id
    except KeyError:
        st.warning("⚠️ Streamlit secretsで楽天設定が見つかりません")
    except Exception as e:
        st.warning(f"⚠️ Streamlit secrets読み込みエラー: {e}")
    
    # 方法2: 環境変数
    try:
        api_key = os.getenv("RAKUTEN_APPLICATION_ID")
        affiliate_id = os.getenv("RAKUTEN_AFFILIATE_ID")
        if api_key and affiliate_id:
            st.success("✅ 環境変数から設定を読み込みました")
            return api_key, affiliate_id
        else:
            st.warning("⚠️ 環境変数に楽天設定が見つかりません")
    except Exception as e:
        st.warning(f"⚠️ 環境変数読み込みエラー: {e}")
    
    # 方法3: デフォルト値（開発用）
    if not api_key or not affiliate_id:
        st.error("❌ 楽天APIキーが見つかりません。以下のいずれかの方法で設定してください：")
        st.markdown("""
        **設定方法:**
        1. `.streamlit/secrets.toml` に設定を追加
        2. 環境変数 `RAKUTEN_APPLICATION_ID` と `RAKUTEN_AFFILIATE_ID` を設定
        3. Streamlit Cloud の場合、アプリ設定でSecretsを追加
        """)
        st.stop()
    
    return api_key, affiliate_id

# 設定取得
try:
    API_KEY, AFFILIATE_ID = get_api_keys()
except Exception as e:
    st.error(f"設定エラー: {e}")
    st.stop()


# --- Google Sheets認証 ---
def get_gspread_client():
    try:
        creds = Credentials.from_service_account_info(
            st.secrets["gcp_service_account"],
            scopes=[
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive.readonly"
            ]
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
        return None

    data = response.json()
    page_count = data.get("pageCount", 1)
    books = data.get("Items", [])

    if page_count >= 1:
        num = int(num) + 1
        search_title = search_title.replace("num", str(num))
        for book_item in books:
            book = book_item["Item"]
            if search_title in book["title"]:
                return {
                    "title": book["title"],
                    "volume": str(num),  # 巻数
                    "isbn": book["isbn"],
                    "sales_date": book["salesDate"]
                }
    return None


# --- メイン ---
def main():
    st.title("📚 楽天Books 最新巻チェック")

    # デバッグ情報（開発時のみ表示）
    if st.checkbox("設定情報を表示（デバッグ用）"):
        st.write("**設定状況:**")
        st.write(f"- 楽天API Key: {'✅ 設定済み' if 'API_KEY' in globals() else '❌ 未設定'}")
        st.write(f"- 楽天Affiliate ID: {'✅ 設定済み' if 'AFFILIATE_ID' in globals() else '❌ 未設定'}")
        st.write(f"- Google Cloud認証: {'✅ 設定済み' if 'gcp_service_account' in st.secrets else '❌ 未設定'}")

    # 作品一覧スプレッドシートの存在確認ボタン
    if st.button("📋 「作品一覧」シートの確認"):
        try:
            gc = get_gspread_client()
            st.info("「作品一覧」シートを確認中...")
            try:
                spreadsheet = gc.open(SPREADSHEET_NAME)
                st.success(f"✅ 「{SPREADSHEET_NAME}」シートが見つかりました (ID: {spreadsheet.id})")
            except SpreadsheetNotFound:
                st.error(f"❌ 「{SPREADSHEET_NAME}」シートが見つかりません。スプレッドシート名を確認するか、サービスアカウントにアクセス権限を付与してください。")
        except Exception as e:
            st.error(f"❌ スプレッドシート確認エラー: {e}")

    if st.button("最新刊チェック開始 ▶️"):
        st.info(f"「{SPREADSHEET_NAME}」スプレッドシートを取得中...")

        try:
            gc = get_gspread_client()
            spreadsheet = gc.open(SPREADSHEET_NAME)
            worksheet = spreadsheet.get_worksheet(0)
            st.success(f"✅ スプレッドシート「{SPREADSHEET_NAME}」に接続しました")
        except SpreadsheetNotFound:
            st.error(f"❌ スプレッドシート「{SPREADSHEET_NAME}」が見つかりません。名前を確認するか、上記のボタンでスプレッドシートの確認をしてください。")
            return
        except APIError as e:
            st.error(f"❌ Google Sheets APIエラー: {e}")
            st.markdown("""
            **考えられる原因:**
            - スプレッドシートへのアクセス権限がない
            - Google Sheets APIの利用制限に達した
            - サービスアカウントがスプレッドシートを共有されていない
            
            **解決方法:**
            1. スプレッドシートの共有設定を確認
            2. サービスアカウント（manga-check@my-project-shimakiti-426301.iam.gserviceaccount.com）にアクセス権限を付与
            3. しばらく時間をおいてから再試行
            """)
            return
        except Exception as e:
            st.error(f"❌ 予期しないエラー: {e}")
            return

        # スプレッドシートからデータを取得
        try:
            rows = worksheet.get_all_values()
            if not rows:
                st.warning("⚠️ スプレッドシートにデータがありません")
                return
            st.success(f"✅ {len(rows)-1}件の作品データを取得しました")
        except Exception as e:
            st.error(f"❌ スプレッドシートデータ取得エラー: {e}")
            return

        # データ形式の確認と処理
        try:
            data = []
            for i, row in enumerate(rows[1:], 1):  # ヘッダー行をスキップ
                if len(row) < 3:
                    st.warning(f"⚠️ 行{i+1}: データが不完全です（列数: {len(row)}）")
                    continue
                
                title = row[0].strip() if len(row) > 0 else ""
                search_title = row[1].strip() if len(row) > 1 else ""
                number = row[2].strip() if len(row) > 2 else ""
                
                if not title:
                    st.warning(f"⚠️ 行{i+1}: タイトルが空です")
                    continue
                    
                data.append({
                    "title": title, 
                    "search_title": search_title, 
                    "number": number
                })
            
            if not data:
                st.error("❌ 有効なデータが見つかりません")
                return
                
            st.info(f"📊 {len(data)}件の有効なデータを処理します")
            
        except Exception as e:
            st.error(f"❌ データ処理エラー: {e}")
            return

        # 楽天API検索の実行
        st.subheader("🔎 検索実行中...")
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        results = []  # 検索結果を格納するリスト
        
        for i, item in enumerate(data):
            progress_bar.progress((i + 1) / len(data))
            status_text.text(f"検索中: {item['title']} ({i+1}/{len(data)})")
            
            try:
                params = {
                    'applicationId': API_KEY,
                    'affiliateId': AFFILIATE_ID,
                    'title': item["title"],
                    'sort': '-releaseDate',
                    'hits': 30
                }
                result = get_books(params, item["search_title"], item["number"], 0)
                if result:
                    results.append({
                        "作品名": result["title"],
                        "巻数": result["volume"],
                        "出版日": result["sales_date"],
                        "ISBN": result["isbn"]
                    })
            except Exception as e:
                st.error(f"❌ 「{item['title']}」の検索でエラー: {e}")
                continue
        
        progress_bar.empty()
        status_text.empty()

        # 結果をテーブルで表示
        st.subheader("🔎 検索結果")
        
        if results:
            import pandas as pd
            df = pd.DataFrame(results)
            st.dataframe(df, use_container_width=True)
            st.success(f"✅ {len(results)}件の最新刊が見つかりました！")
        else:
            st.warning("⚠️ 条件に一致する最新刊は見つかりませんでした")

        st.success("✅ 最新刊チェックが完了しました！")


if __name__ == "__main__":
    main()
