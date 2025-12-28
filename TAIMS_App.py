import streamlit as st
import os
import json
import requests
import uuid
from dotenv import load_dotenv
import google.generativeai as genai
import firebase_admin
from firebase_admin import credentials, firestore

# --- 1. CẤU HÌNH ---
st.set_page_config(page_title="TAIMS", page_icon="🎯", layout="wide")

TAIMS_INSTRUCTION = """
Bạn là TAIMS - Trợ lý AI chuyên về Quản lý Thời gian.
Nguyên tắc: Tên là TAIMS. Trả lời ngắn gọn, tập trung giải pháp.
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

# --- 4. DATA LOGIC ---
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
        # Nếu thiếu Index Session -> Báo lỗi bên Sidebar
        if "requires an index" in str(e):
            try:
                link = str(e).split("https://")[1].split(" ")[0]
                st.sidebar.error("⚠️ Thiếu Index 1 (Session)")
                st.sidebar.link_button("👉 Tạo Index 1", f"https://{link}")
            except: pass
        return []

def load_chat_history(session_id):
    if not db: return []
    try:
        docs = db.collection("chat_logs").where("session_id", "==", session_id).order_by("timestamp", direction=firestore.Query.ASCENDING).stream()
        return [{"role": doc.to_dict()["role"], "content": doc.to_dict()["content"]} for doc in docs]
    except Exception as e:
        # Nếu thiếu Index Chat -> Báo lỗi trực tiếp
        if "requires an index" in str(e):
            st.error("⚠️ Thiếu Index 2 (Chat Logs)")
            try:
                link = str(e).split("https://")[1].split(" ")[0]
                st.link_button("👉 Bấm vào đây để Tạo Index 2", f"https://{link}")
            except: pass
        return []

# --- 5. AUTH ---
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

# --- 6. GIAO DIỆN ---
if "user_info" not in st.session_state: st.session_state.user_info = None
if "current_session_id" not in st.session_state: st.session_state.current_session_id = str(uuid.uuid4())
if "chat_history" not in st.session_state: st.session_state.chat_history = []

if not st.session_state.user_info:
    # MÀN HÌNH LOGIN
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.title("TAIMS 🎯")
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
    # MÀN HÌNH CHÍNH
    uid = st.session_state.user_info["uid"]
    
    with st.sidebar:
        if st.button("➕ Chat Mới"): st.session_state.current_session_id = str(uuid.uuid4()); st.session_state.chat_history = []; st.rerun()
        st.divider()
        sessions = load_user_sessions(uid)
        for s in sessions:
            if st.button(f"📝 {s.get('title','...')}", key=s['id']): 
                st.session_state.current_session_id = s['id']
                st.session_state.chat_history = load_chat_history(s['id'])
                st.rerun()
        st.divider()
        if st.button("Logout"): st.session_state.user_info = None; st.rerun()

    st.title("TAIMS 🎯")

    # Load history nếu F5
    if not st.session_state.chat_history and db:
        st.session_state.chat_history = load_chat_history(st.session_state.current_session_id)

    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]): st.markdown(msg["content"])

    if prompt := st.chat_input("Cùng TAIMS thiết kế lộ trình..."):
        # 1. Hiện User & Lưu
        st.session_state.chat_history.append({"role": "user", "content": prompt})
        with st.chat_message("user"): st.markdown(prompt)
        save_message(uid, st.session_state.current_session_id, "user", prompt)

        # 2. AI Xử lý
        with st.chat_message("assistant"):
            with st.spinner("..."):
                try:
                    # Chuẩn bị context
                    history_for_ai = []
                    for m in st.session_state.chat_history:
                        role = "model" if m["role"]=="assistant" else "user"
                        history_for_ai.append({"role": role, "parts": [m["content"]]})
                    
                    # Gọi AI
                    model = genai.GenerativeModel("models/gemini-1.5-flash", system_instruction=TAIMS_INSTRUCTION)
                    chat = model.start_chat(history=history_for_ai)
                    response = chat.send_message(prompt)
                    reply = response.text
                    
                    st.markdown(reply)
                    
                    # Lưu AI & Rerun
                    st.session_state.chat_history.append({"role": "assistant", "content": reply})
                    save_message(uid, st.session_state.current_session_id, "assistant", reply)
                    st.rerun() # <--- CHỈ RERUN KHI THÀNH CÔNG

                except Exception as e:
                    # NẾU LỖI: IN RA MÀN HÌNH VÀ KHÔNG RERUN
                    st.error(f"❌ Lỗi AI: {e}")
                    
                    # Bắt lỗi Index cụ thể ở đây
                    if "requires an index" in str(e):
                        st.warning("⚠️ Firebase cần tạo Index để AI đọc được lịch sử!")
                        try:
                            link = str(e).split("https://")[1].split(" ")[0]
                            st.link_button("👉 Bấm vào đây tạo Index ngay", f"https://{link}")
                        except: pass
