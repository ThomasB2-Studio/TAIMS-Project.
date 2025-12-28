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

# --- 2. NHÂN CÁCH AI ---
TAIMS_INSTRUCTION = """
IDENTITY:
Bạn là TAIMS - Chuyên gia tối ưu hóa hiệu suất và Xử lý dữ liệu (Data Processor).

NHIỆM VỤ:
1. Lập kế hoạch: Biến mục tiêu thành hành động.
2. Xử lý Thời Khóa Biểu: Nếu người dùng gửi text lộn xộn, hãy phân tích thành bảng rõ ràng.

QUY TẮC:
- Dữ liệu lịch học: Kẻ bảng Markdown (Thứ | Tiết | Môn | Phòng | GV).
- Kế hoạch: Dùng gạch đầu dòng.
- Ngắn gọn, tập trung.
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
    st.error("❌ Thiếu Gemini API Key. Kiểm tra file .env hoặc Secrets.")
    st.stop()

# Cấu hình Gemini
try:
    genai.configure(api_key=api_key)
except Exception as e:
    st.error(f"Lỗi cấu hình Key: {e}")

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
        except: return None
        return None
    except: return None

db = init_connection()

# --- 5. HÀM XỬ LÝ DB ---
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
    except: pass

def load_user_sessions(uid):
    if not db: return []
    try:
        docs = db.collection("sessions").where("uid", "==", uid).order_by("last_updated", direction=firestore.Query.DESCENDING).stream()
        return [{"id": doc.id, **doc.to_dict()} for doc in docs]
    except Exception as e:
        if "requires an index" in str(e):
            st.sidebar.error("⚠️ Cần tạo Index (Sessions)!")
        return []

def load_chat_history(session_id):
    if not db: return []
    try:
        docs = db.collection("chat_logs").where("session_id", "==", session_id).order_by("timestamp", direction=firestore.Query.ASCENDING).stream()
        return [{"role": doc.to_dict()["role"], "content": doc.to_dict()["content"]} for doc in docs]
    except Exception as e:
        if "requires an index" in str(e):
            st.error("⚠️ Cần tạo Index (Chat Logs)!")
        return []

def delete_session_from_db(session_id):
    if not db: return
    try:
        db.collection("sessions").document(session_id).delete()
        logs = db.collection("chat_logs").where("session_id", "==", session_id).stream()
        for log in logs: log.reference.delete()
        return True
    except: return False

# --- 6. HÀM EXCEL (ENGINE: OPENPYXL - AN TOÀN NHẤT) ---
def generate_excel_from_text(text):
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        prompt = f"""
        Trích xuất dữ liệu từ văn bản sau thành JSON list.
        Text: {text[:4000]}
        Yêu cầu:
        - TKB Đại học: [Thứ, Tiết, Môn Học, Phòng, Giảng Viên]
        - To-Do List: [Ngày, Giờ, Công Việc, Trạng Thái]
        CHỈ TRẢ VỀ JSON THUẦN (List of Objects). KHÔNG MARKDOWN.
        """
        response = model.generate_content(prompt)
        json_str = response.text.strip()
        if "
