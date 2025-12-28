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

# --- 2. KIỂM TRA CHÌA KHÓA (DEBUG) ---
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
web_api_key = os.getenv("FIREBASE_WEB_API_KEY")

def get_secret(key_name):
    try: return st.secrets[key_name]
    except: return None

# Ưu tiên lấy từ Secrets nếu không có trong env
if not api_key: api_key = get_secret("GEMINI_API_KEY")
if not web_api_key: web_api_key = get_secret("FIREBASE_WEB_API_KEY")

# --- BÁO LỖI NẾU THIẾU KEY ---
if not api_key:
    st.error("❌ LỖI NGHIÊM TRỌNG: Không tìm thấy GEMINI_API_KEY!")
    st.info("👉 Hãy kiểm tra lại file Secrets. Đảm bảo dòng GEMINI_API_KEY nằm ở TRÊN CÙNG, không nằm dưới [FIREBASE].")
    st.stop()

try:
    genai.configure(api_key=api_key)
except Exception as e:
    st.error(f"❌ Key Gemini bị lỗi: {e}")

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

# --- 4. HÀM XỬ LÝ DỮ LIỆU (CÓ BẮT LỖI INDEX) ---
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
    except Exception as e:
        st.error(f"Lỗi khi lưu: {e}")

def load_user_sessions(uid):
    if not db: return []
    try:
        docs = db.collection("sessions").where("uid", "==", uid).order_by("last_updated", direction=firestore.Query.DESCENDING).stream()
        return [{"id": doc.id, **doc.to_dict()} for doc in docs]
    except Exception as e:
        if "requires an index" in str(e):
            st.sidebar.error("⚠️ Thiếu Index Sessions!")
            try:
                link = str(e).split("https://")[1].split(" ")[0]
                st.sidebar.link_button("👉 Tạo Index 1", f"https://{link}")
            except: pass
        return []

def load_chat_history(session_id):
    if not db: return []
    try:
        # Index số 2 thường thiếu ở đây
        docs = db.collection("chat_logs").where("session_id", "==", session_id).order_by("timestamp", direction=firestore.Query.ASCENDING).stream()
        return [{"role": doc.to_dict()["role"], "content": doc.to_dict()["content"]} for doc in docs]
    except Exception as e:
        if "requires an index" in str(e):
            st.error("⚠️ Thiếu Index Chat Logs (AI không đọc được quá khứ)!")
            try:
                link = str(e).split("https://")[1].split(" ")[0]
                st.link_button("👉 Bấm vào đây để Tạo Index số 2", f"https://{link}")
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
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.title("TAIMS 🎯")
        tab1, tab2 = st.tabs(["Đăng Nhập", "Đăng Ký"])
        with tab1:
            email = st.text_input("Email", key="l_e"); pwd = st.text_input("Pass", type="password", key="l_p")
            if st.button("Login", use_container_width=True):
                resp = sign_in(email, pwd)
                if "localId" in resp: st.session_state.user_info = {"uid": resp["localId"], "email": resp["email"]}; st.rerun()
                else: st.error("Sai thông tin")
        with tab2:
            email = st.text_input("Email", key="r_e"); pwd = st.text_input("Pass", type="password", key="r_p")
            if st.button("Register", use_container_width=True):
                resp = sign_up(email, pwd)
                if "localId" in resp: st.session_state.user_info = {"uid": resp["localId"], "email": resp["email"]}; st.success("OK"); st.rerun()
                else: st.error("Lỗi đăng ký")
else:
    uid = st.session_state.user_info["uid"]
    with st.sidebar:
        if st.button("➕ Chat Mới"): st.session_state.current_session_id = str(uuid.uuid4()); st.session_state.chat_history = []; st.rerun()
        st.divider()
        for s in load_user_sessions(uid):
            if st.button(f"📝 {s.get('title','...')}", key=s['id']): 
                st.session_state.current_session_id = s['id']
                st.session_state.chat_history = load_chat_history(s['id'])
                st.rerun()
        st.divider()
        if st.button("Logout"): st.session_state.user_info = None; st.rerun()

    st.title("TAIMS 🎯")
    
    # Load history nếu trống (quan trọng khi F5)
    if not st.session_state.chat_history and db:
        st.session_state.chat_history = load_chat_history(st.session_state.current_session_id)

    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]): st.markdown(msg["content"])

    if prompt := st.chat_input("..."):
        st.session_state.chat_history.append({"role": "user", "content": prompt})
        with st.chat_message("user"): st.markdown(prompt)
        save_message(uid, st.session_state.current_session_id, "user", prompt)

        with st.chat_message("assistant"):
            try:
                # --- DEBUG AI ---
                gh = [{"role": "model" if m["role"]=="assistant" else "user", "parts": [m["content"]]} for m in st.session_state.chat_history]
                model = genai.GenerativeModel("models/gemini-1.5-flash", system_instruction=TAIMS_INSTRUCTION)
                response = model.generate_content(gh) # Dùng generate_content thay vì chat session để debug dễ hơn
                reply = response.text
                st.markdown(reply)
                st.session_state.chat_history.append({"role": "assistant", "content": reply})
                save_message(uid, st.session_state.current_session_id, "assistant", reply)
            except Exception as e:
                st.error(f"❌ AI Chết lâm sàng: {e}")
                if "API_KEY" in str(e): st.info("Kiểm tra lại Key Gemini trong Secrets!")
        st.rerun()
