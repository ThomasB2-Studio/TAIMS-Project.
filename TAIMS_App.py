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

# --- 1. CẤU HÌNH ---
st.set_page_config(page_title="TAIMS", page_icon="🎯", layout="wide")

TAIMS_INSTRUCTION = """
IDENTITY:
Bạn là TAIMS - Chuyên gia tối ưu hóa hiệu suất và Xử lý dữ liệu (Data Processor).

NHIỆM VỤ:
1. Lập kế hoạch: Biến mục tiêu thành hành động.
2. Xử lý Thời Khóa Biểu: Nếu người dùng gửi text lộn xộn, hãy phân tích và sắp xếp nó lại thành bảng rõ ràng.

QUY TẮC:
- Dữ liệu lịch học: Kẻ bảng Markdown (Thứ | Tiết | Môn | Phòng | GV).
- Kế hoạch: Dùng gạch đầu dòng.
- Ngắn gọn, tập trung.
"""

# --- 2. LOAD KEYS ---
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
web_api_key = os.getenv("FIREBASE_WEB_API_KEY")

def get_secret(key_name):
    try: return st.secrets[key_name]
    except: return None

if not api_key: api_key = get_secret("GEMINI_API_KEY")
if not web_api_key: web_api_key = get_secret("FIREBASE_WEB_API_KEY")

if not api_key: st.error("❌ Thiếu Gemini API Key"); st.stop()

try: genai.configure(api_key=api_key)
except: pass

# --- 3. KẾT NỐI DB ---
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

# --- 4. DATA LOGIC (CÓ HÀM XÓA) ---
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

def delete_session_from_db(session_id):
    if not db: return
    try:
        # Xóa Session
        db.collection("sessions").document(session_id).delete()
        # Xóa Logs (Firestore cần xóa từng cái)
        logs = db.collection("chat_logs").where("session_id", "==", session_id).stream()
        for log in logs: log.reference.delete()
        return True
    except: return False

def load_user_sessions(uid):
    if not db: return []
    try:
        docs = db.collection("sessions").where("uid", "==", uid).order_by("last_updated", direction=firestore.Query.DESCENDING).stream()
        return [{"id": doc.id, **doc.to_dict()} for doc in docs]
    except Exception as e:
        if "requires an index" in str(e): st.sidebar.error("⚠️ Cần tạo Index (Sessions)!")
        return []

def load_chat_history(session_id):
    if not db: return []
    try:
        docs = db.collection("chat_logs").where("session_id", "==", session_id).order_by("timestamp", direction=firestore.Query.ASCENDING).stream()
        return [{"role": doc.to_dict()["role"], "content": doc.to_dict()["content"]} for doc in docs]
    except Exception as e:
        if "requires an index" in str(e): st.error("⚠️ Cần tạo Index (Chat Logs)!")
        return []

# --- 5. EXCEL LOGIC ---
def generate_excel_from_text(text):
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        prompt = f"Trích xuất JSON từ text sau (Lịch học hoặc To-do list):\n{text[:4000]}\nOutput JSON Only."
        response = model.generate_content(prompt)
        json_str = response.text.strip().replace("```json", "").replace("```", "")
        data = json.loads(json_str)
        df = pd.DataFrame(data)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False)
        return output.getvalue()
    except Exception as e: print(e); return None

# --- 6. AUTH ---
def sign_in(email, password):
    try:
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={web_api_key}"
        return requests.post(url, json={"email": email, "password": password, "returnSecureToken": True}).json()
    except: return {"error": "Lỗi kết nối"}

def sign_up(email, password):
    try:
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={web_api_key}"
        return requests.post(url, json={"email": email, "password": password, "returnSecureToken": True}).json()
    except: return {"error": "Lỗi kết nối"}

# --- 7. UI HELPER ---
def truncate_text(text, max_len=25):
    if len(text) > max_len: return text[:max_len] + "..."
    return text

# --- 8. GIAO DIỆN ---
if "user_info" not in st.session_state: st.session_state.user_info = None
if "current_session_id" not in st.session_state: st.session_state.current_session_id = str(uuid.uuid4())
if "chat_history" not in st.session_state: st.session_state.chat_history = []

if not st.session_state.user_info:
    # --- MÀN HÌNH ĐĂNG NHẬP (ĐÃ SỬA CAPTION) ---
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.title("TAIMS 🎯")
        st.caption("Target Action Integrated Management System") # <--- ĐÃ SỬA CHUẨN
        
        tab1, tab2 = st.tabs(["Đăng Nhập", "Đăng Ký"])
        with tab1:
            e = st.text_input("Email", key="le"); p = st.text_input("Pass", type="password", key="lp")
            if st.button("Vào", use_container_width=True):
                resp = sign_in(e, p)
                if "localId" in resp: st.session_state.user_info = {"uid": resp["localId"], "email": resp["email"]}; st.rerun()
                else: st.error("Sai thông tin")
        with tab2:
            e = st.text_input("Email", key="re"); p = st.text_input("Pass", type="password", key="rp")
            if st.button("Tạo", use_container_width=True):
                resp = sign_up(e, p)
                if "localId" in resp: st.session_state.user_info = {"uid": resp["localId"], "email": resp["email"]}; st.success("OK"); st.rerun()
                else: st.error("Lỗi đăng ký")
else:
    # --- MÀN HÌNH CHÍNH ---
    uid = st.session_state.user_info["uid"]
    
    with st.sidebar:
        if st.button("➕ Chat Mới", type="primary", use_container_width=True):
            st.session_state.current_session_id = str(uuid.uuid4()); st.session_state.chat_history = []; st.rerun()
        
        st.divider()
        # --- DANH SÁCH LỊCH SỬ (CÓ NÚT XÓA) ---
        sessions = load_user_sessions(uid)
        for s in sessions:
            col_view, col_del = st.columns([0.85, 0.15])
            with col_view:
                title = truncate_text(s.get('title', '...'))
                if s['id'] == st.session_state.current_session_id:
                    st.button(f"🟢 {title}", key=f"v_{s['id']}", disabled=True, use_container_width=True)
                else:
                    if st.button(f"📄 {title}", key=f"v_{s['id']}", use_container_width=True):
                        st.session_state.current_session_id = s['id']; st.session_state.chat_history = load_chat_history(s['id']); st.rerun()
            with col_del:
                if st.button("🗑️", key=f"d_{s['id']}"): # <--- NÚT XÓA ĐÃ TRỞ LẠI
                    delete_session_from_db(s['id'])
                    if s['id'] == st.session_state.current_session_id:
                        st.session_state.current_session_id = str(uuid.uuid4()); st.session_state.chat_history = []
                    st.rerun()
                    
        st.divider()
        if st.button("Đăng xuất", use_container_width=True): st.session_state.user_info = None; st.rerun()

    st.title("TAIMS 🎯")
    # Đảm bảo caption main cũng đúng
    st.caption("Target Action Integrated Management System")

    if not st.session_state.chat_history and db:
        st.session_state.chat_history = load_chat_history(st.session_state.current_session_id)

    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg["role"] == "assistant":
                # Nút Excel
                if "thứ" in msg["content"].lower() or "ngày" in msg["content"].lower():
                    xl_key = f"xl_{hash(msg['content'])}"
                    if st.button("📥 Xuất Excel", key=xl_key):
                        with st.spinner("..."):
                            d = generate_excel_from_text(msg["content"])
                            if d: st.download_button("👉 Tải về", d, "TAIMS.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key=f"dl_{xl_key}")
                # Checklist
                tasks = re.findall(r'[-*]\s+(.*)', msg["content"])
                if tasks and len(tasks) > 2:
                    with st.expander("✅ Checklist"):
                        for i, t in enumerate(tasks): st.checkbox(t, key=f"c_{hash(msg['content'])}_{i}")

    if prompt := st.chat_input("..."):
        st.session_state.chat_history.append({"role": "user", "content": prompt})
        with st.chat_message("user"): st.markdown(prompt)
        save_message(uid, st.session_state.current_session_id, "user", prompt)

        with st.chat_message("assistant"):
            with st.spinner("..."):
                try:
                    # GỌI TRỰC TIẾP - KHÔNG GIẤU LỖI
                    gh = [{"role": "model" if m["role"]=="assistant" else "user", "parts": [m["content"]]} for m in st.session_state.chat_history]
                    
                    # Thử Flash trước
                    try:
                        model = genai.GenerativeModel("gemini-1.5-flash", system_instruction=TAIMS_INSTRUCTION)
                        response = model.generate_content(gh) # Dùng generate_content thay vì chat session để dễ debug
                        reply = response.text
                    except Exception as e1:
                        # Nếu lỗi, thử Pro
                        st.warning(f"Flash lỗi ({e1}), thử Pro...")
                        model = genai.GenerativeModel("gemini-pro")
                        response = model.generate_content(gh)
                        reply = response.text

                    st.markdown(reply)
                    st.session_state.chat_history.append({"role": "assistant", "content": reply})
                    save_message(uid, st.session_state.current_session_id, "assistant", reply)
                    time.sleep(0.5); st.rerun()
                except Exception as e:
                    # IN LỖI CHI TIẾT RA MÀN HÌNH
                    st.error(f"⚠️ Lỗi AI Chi Tiết: {e}")
