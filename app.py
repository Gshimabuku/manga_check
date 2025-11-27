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
from datetime import datetime
import re

# --- APIキー・認証設定 ---
API_ENDPOINT = "https://app.rakuten.co.jp/services/api/BooksBook/Search/20170404"
SPREADSHEET_NAME = st.secrets["env"]["sheet_name"]  # スプレッドシート名

# シークレット設定の確認とエラーハンドリング
def get_api_keys():
    api_key = None
    affiliate_id = None

    # Streamlit secrets から設定値を取得
    try:
        api_key = st.secrets["rakuten"]["applicationId"]
        affiliate_id = st.secrets["rakuten"]["affiliateId"]
        return api_key, affiliate_id
    except KeyError:
        st.warning("⚠️ Streamlit secretsで楽天BooksAPIの設定が見つかりません")
    except Exception as e:
        st.warning(f"⚠️ Streamlit secrets読み込みエラー: {e}")
    
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

# --- 日付判定 ---
def is_past(date_str: str) -> bool:
    test = datetime(2026, 5, 1)
    st.info(test)
    # today = datetime.now().date()
    today = test.date()
    st.info(today)

    # --- 1) 日付ありパターン（YYYY年MM月DD日） ---
    full_date = re.match(r"(\d{4}年\d{1,2}月\d{1,2}日)", date_str)
    if full_date:
        pure_date = full_date.group(1)
        target_date = datetime.strptime(pure_date, "%Y年%m月%d日").date()
        return target_date < today

    # --- 2) 日付なし（月までの表記）例：「2025年05月下旬」「2025年05月」 ---
    month_only = re.match(r"(\d{4}年\d{1,2}月)", date_str)
    if month_only:
        pure_month = month_only.group(1)
        target_month = datetime.strptime(pure_month, "%Y年%m月").date()

        # 月比較：年と月で判定する
        today_year_month = today.year * 100 + today.month
        target_year_month = target_month.year * 100 + target_month.month

        return target_year_month < today_year_month

    raise ValueError(f"日付形式を解釈できません: {date_str}")


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
            if is_past(book["salesDate"]):
                if search_title in book["title"]:
                    return {
                        "title": book["title"],
                        "volume": str(num),  # 巻数
                        "isbn": book["isbn"],
                        "sales_date": book["salesDate"]
                    }
    return None


# --- スプレッドシート更新機能 ---
def update_spreadsheet(gc, worksheet, original_data, results):
    """検索結果をもとにスプレッドシートの巻数を更新する"""
    updated_count = 0
    
    for result in results:
        original_index = result["original_index"]
        new_volume = result["巻数"]
        original_item = original_data[original_index]
        current_volume = original_item["number"]
        
        # 巻数が異なる場合のみ更新
        if str(new_volume) != str(current_volume):
            # 行番号は1ベースで、ヘッダー行を考慮して+2
            row_num = original_index + 2
            worksheet.update_cell(row_num, 3, str(new_volume))  # 3列目が巻数
            updated_count += 1
            st.write(f"更新: {original_item['title']} の巻数を {current_volume} → {new_volume} に変更")
    
    if updated_count == 0:
        st.info("更新する必要のある巻数はありませんでした")
    else:
        st.success(f"{updated_count}件の巻数を更新しました")


# --- メイン ---
def main():
    st.title("📚 最新巻チェック")

    # セッション状態の初期化
    if 'search_results' not in st.session_state:
        st.session_state.search_results = None
    if 'original_data' not in st.session_state:
        st.session_state.original_data = None
    if 'worksheet' not in st.session_state:
        st.session_state.worksheet = None
    if 'gc' not in st.session_state:
        st.session_state.gc = None

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
                st.success(f"✅ 「{SPREADSHEET_NAME}」シートが見つかりました")
            except SpreadsheetNotFound:
                st.error(f"❌ 「{SPREADSHEET_NAME}」シートが見つかりません。スプレッドシート名を確認するか、サービスアカウントにアクセス権限を付与してください。")
        except Exception as e:
            st.error(f"❌ スプレッドシート確認エラー: {e}")
    
    # スプレッドシートの内容確認ボタン
    if st.button("📄 スプレッドシートの内容確認"):
        try:
            gc = get_gspread_client()
            st.info("スプレッドシートの内容を取得中...")
            try:
                spreadsheet = gc.open(SPREADSHEET_NAME)
                worksheet = spreadsheet.get_worksheet(0)
                rows = worksheet.get_all_values()
                
                if not rows:
                    st.warning("⚠️ スプレッドシートにデータがありません")
                else:
                    import pandas as pd
                    # ヘッダー行がある場合は最初の行をヘッダーとして使用
                    if len(rows) > 1:
                        df = pd.DataFrame(rows[1:], columns=rows[0])
                        st.success(f"✅ {len(rows)-1}件のデータを取得しました")
                    else:
                        df = pd.DataFrame(rows)
                        st.success(f"✅ {len(rows)}件のデータを取得しました")
                    
                    st.subheader("📊 スプレッドシートの内容")
                    st.dataframe(df, use_container_width=True)
                    
            except SpreadsheetNotFound:
                st.error(f"❌ 「{SPREADSHEET_NAME}」シートが見つかりません。スプレッドシート名を確認するか、サービスアカウントにアクセス権限を付与してください。")
        except Exception as e:
            st.error(f"❌ スプレッドシート内容取得エラー: {e}")

    if st.button("最新刊チェック開始 ▶️"):
        # 進捗表示用のプレースホルダーを作成
        progress_placeholder = st.empty()
        
        with progress_placeholder.container():
            st.info(f"「{SPREADSHEET_NAME}」スプレッドシートを取得中...")

        try:
            gc = get_gspread_client()
            spreadsheet = gc.open(SPREADSHEET_NAME)
            worksheet = spreadsheet.get_worksheet(0)
            
            with progress_placeholder.container():
                st.success(f"✅ スプレッドシート「{SPREADSHEET_NAME}」に接続しました")
        except SpreadsheetNotFound:
            progress_placeholder.empty()
            st.error(f"❌ スプレッドシート「{SPREADSHEET_NAME}」が見つかりません。名前を確認するか、上記のボタンでスプレッドシートの確認をしてください。")
            return
        except APIError as e:
            progress_placeholder.empty()
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
            progress_placeholder.empty()
            st.error(f"❌ 予期しないエラー: {e}")
            return

        # スプレッドシートからデータを取得
        try:
            rows = worksheet.get_all_values()
            if not rows:
                progress_placeholder.empty()
                st.warning("⚠️ スプレッドシートにデータがありません")
                return
            
            with progress_placeholder.container():
                st.success(f"✅ {len(rows)-1}件の作品データを取得しました")
        except Exception as e:
            progress_placeholder.empty()
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
                progress_placeholder.empty()
                st.error("❌ 有効なデータが見つかりません")
                return
                
            with progress_placeholder.container():
                st.info(f"📊 {len(data)}件の有効なデータを処理します")
            
        except Exception as e:
            progress_placeholder.empty()
            st.error(f"❌ データ処理エラー: {e}")
            return

        # 楽天API検索の実行
        with progress_placeholder.container():
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
                        "original_index": i,  # 元データのインデックス
                        "original_title": item["title"],  # 元のタイトル
                        "作品名": result["title"],
                        "巻数": result["volume"],
                        "出版日": result["sales_date"],
                        "ISBN": result["isbn"]
                    })
            except Exception as e:
                st.error(f"❌ 「{item['title']}」の検索でエラー: {e}")
                continue
        
        # 進捗表示をクリア
        progress_placeholder.empty()

        # 検索結果をセッション状態に保存
        st.session_state.search_results = results
        st.session_state.original_data = data
        st.session_state.worksheet = worksheet
        st.session_state.gc = gc

    # 検索結果の表示（セッション状態から）
    if st.session_state.search_results is not None:
        # 結果をテーブルで表示
        st.subheader("🔎 検索結果")
        
        if st.session_state.search_results:
            import pandas as pd
            # 表示用のDataFrameを作成（内部データを除外）
            display_results = [{k: v for k, v in result.items() 
                              if k not in ["original_index", "original_title"]} 
                             for result in st.session_state.search_results]
            df = pd.DataFrame(display_results)
            st.dataframe(df, use_container_width=True)
            st.success(f"✅ {len(st.session_state.search_results)}件の最新刊が見つかりました！")
            
            # ボタンを並べて配置
            col1, col2 = st.columns(2)
            
            with col1:
                # スプレッドシート更新ボタン
                if st.button("📝 スプレッドシートを更新"):
                    try:
                        st.info("スプレッドシートを更新中...")
                        update_spreadsheet(st.session_state.gc, st.session_state.worksheet, 
                                         st.session_state.original_data, st.session_state.search_results)
                        st.success("✅ スプレッドシートの更新が完了しました！")
                    except Exception as e:
                        st.error(f"❌ スプレッドシート更新エラー: {e}")
            
            with col2:
                # 結果をクリアするボタン
                if st.button("🗑️ 検索結果をクリア"):
                    st.session_state.search_results = None
                    st.session_state.original_data = None
                    st.session_state.worksheet = None
                    st.session_state.gc = None
                    st.rerun()
        else:
            st.warning("⚠️ 条件に一致する最新刊は見つかりませんでした")

        st.success("✅ 最新刊チェックが完了しました！")


if __name__ == "__main__":
    main()
