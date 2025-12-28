import streamlit as st
import os
import json
import requests
import uuid
import time
import pandas as pd
import io
import re
from dotenv import load_dotenv
import google.generativeai as genai
import firebase_admin
from firebase_admin import credentials, firestore

# --- 1. CẤU HÌNH TRANG ---
st.set_page_config(page_title="TAIMS", page_icon="🎯", layout="wide")

# --- 2. CẤU HÌNH NHÂN CÁCH AI (BẢN CHI TIẾT CẬU THÍCH) ---
TAIMS_INSTRUCTION = """
IDENTITY:
Bạn là TAIMS - Chuyên gia tối ưu hóa hiệu suất và Xử lý dữ liệu (Data Processor).

NHIỆM VỤ:
1.  **Lập kế hoạch:** Biến mục tiêu thành hành động.
2.  **Xử lý Thời Khóa Biểu:** Nếu người dùng gửi một đoạn văn bản copy từ web trường học (rất lộn xộn), hãy phân tích và sắp xếp nó lại thành bảng rõ ràng.

QUY TẮC TRẢ LỜI:
-   Nếu là dữ liệu lịch học: Hãy kẻ bảng Markdown (Thứ | Tiết | Môn | Phòng | GV).
-   Nếu là kế hoạch thường: Dùng gạch đầu dòng.
-   Luôn ngắn gọn, tập trung.

VÍ DỤ XỬ LÝ LỊCH HỌC:
Input: "Pháp luật đại cương 2 tín chỉ Thứ 7 tiết 8-9 phòng F303"
Output:
| Thứ | Tiết | Môn Học | Phòng | Giảng Viên |
|---|---|---|---|---|
| 7 | 8-9 | Pháp luật đại cương | F303 | ... |
"""

# --- 3. XỬ LÝ API KEYS ---
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
web_api_key = os.getenv("FIREBASE_WEB_API_KEY")

def get_secret(key_name):
    try: return st.secrets[key_name]
    except: return None

if not api_key: api_key = get_secret("GEMINI_API_KEY")
if not web_api_key: web_api_key = get_secret("FIREBASE_WEB_API_KEY")

if not api_key:
    st.error("❌ Thiếu Gemini API Key. Vui lòng kiểm tra file .env hoặc Secrets.")
    st.stop()

try: genai.configure(api_key=api_key)
except Exception as e: st.error(f"Lỗi cấu hình Gemini: {e}")

# --- 4. KẾT NỐI DATABASE ---
@st.cache_resource
def init_connection():
    try:
        if firebase_admin._apps: return firestore.client()
        if os.path.exists("service_account.json"):
            cred = credentials.Certificate("service_account.json")
            firebase_admin.initialize_app(cred)
            return firestore.client()
        try:
            if "FIREBASE" in st.secrets:
                key_content = st.secrets["FIREBASE"]["credentials_json"]
                key_dict = json.loads(key_content, strict=False)
                cred = credentials.Certificate(key_dict)
                firebase_admin.initialize_app(cred)
                return firestore.client()
        except Exception: return None
        return None
    except Exception: return None

db = init_connection()

# --- 5. CÁC HÀM XỬ LÝ DATABASE ---
def save_message(uid, session_id, role, content):
    if not db: return
    try:
        db.collection("chat_logs").add({
            "uid": uid, "session_id": session_id, "role": role, "content": content, "timestamp": firestore.SERVER_TIMESTAMP
        })
        if role == "user":
            title = (content[:40] + "...") if len(content) > 40 else content
            db.collection("sessions").document(session_id).set({
                "uid": uid, "session_id": session_id, "title": title, "last_updated": firestore.SERVER_TIMESTAMP
            }, merge=True)
    except Exception as e: print(f"Lỗi lưu DB: {e}")

def load_user_sessions(uid):
    if not db: return []
    try:
        docs = db.collection("sessions").where("uid", "==", uid).order_by("last_updated", direction=firestore.Query.DESCENDING).stream()
        return [{"id": doc.id, **doc.to_dict()} for doc in docs]
    except Exception as e:
        if "requires an index" in str(e):
            st.sidebar.warning("⚠️ Đang tạo Index... Vui lòng chờ.")
        return []

def load_chat_history(session_id):
    if not db: return []
    try:
        docs = db.collection("chat_logs").where("session_id", "==", session_id).order_by("timestamp", direction=firestore.Query.ASCENDING).stream()
        return [{"role": doc.to_dict()["role"], "content": doc.to_dict()["content"]} for doc in docs]
    except Exception: return []

def delete_session_from_db(session_id):
    if not db: return
    try:
        db.collection("sessions").document(session_id).delete()
        logs = db.collection("chat_logs").where("session_id", "==", session_id).stream()
        for log in logs: log.reference.delete()
        return True
    except Exception as e: st.error(f"Lỗi xóa: {e}"); return False

# --- 6. HÀM EXCEL (PHIÊN BẢN ĐẠI HỌC - XlsxWriter) ---
def generate_excel_from_text(text):
    """
    Dùng AI phụ để trích xuất dữ liệu, đặc biệt tối ưu cho text TKB lộn xộn.
    """
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        prompt = f"""
        Bạn là Data Processor. Nhiệm vụ: Biến đoạn văn bản lộn xộn sau thành JSON list chuẩn xác.
        VĂN BẢN ĐẦU VÀO: 
        {text[:4000]}
        
        YÊU CẦU XỬ LÝ:
        1. ƯU TIÊN 1: Nếu là Thời Khóa Biểu Đại Học (có STT, Tín chỉ, Thứ, Tiết...):
           - Trích xuất các cột "Thứ", "Tiết", "Môn Học", "Phòng", "Giảng Viên".
           - Hãy lọc bỏ các thông tin rác, chỉ giữ lại thông tin lịch học.
        2. ƯU TIÊN 2: Nếu là To-Do List thường: Cột "Ngày", "Giờ", "Công Việc", "Trạng Thái".

        OUTPUT FORMAT: Chỉ trả về chuỗi JSON thuần (List of Objects). KHÔNG dùng Markdown.
        """
        response = model.generate_content(prompt)
        
        # Làm sạch JSON
        json_str = response.text.strip()
        if "
