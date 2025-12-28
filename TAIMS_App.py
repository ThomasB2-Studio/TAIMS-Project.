import streamlit as st
import os
import json
import requests
import uuid
import datetime
from dotenv import load_dotenv
import google.generativeai as genai
import firebase_admin
from firebase_admin import credentials, firestore

# --- 1. CẤU HÌNH TRANG ---
st.set_page_config(page_title="TAIMS", page_icon="🎯", layout="wide")

# --- 2. CẤU HÌNH NHÂN CÁCH AI ---
TAIMS_INSTRUCTION = """
Bạn là TAIMS - Trợ lý AI chuyên về Quản lý Thời gian và Hiệu suất.
Nhiệm vụ: Biến mục tiêu thành Kế hoạch hành động.
Nguyên tắc:
- Tên là TAIMS.
- Trả lời ngắn gọn, tập trung vào giải pháp (How-to).
- Không nói đạo lý sáo rỗng.
Tuyệt đối không tự nhận là con người.
"""

# --- 3. LOAD KEYS (AN TOÀN) ---
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

# --- 5. HÀM XỬ LÝ DỮ LIỆU (QUAN TRỌNG VỀ BẢO MẬT) ---

def save_message(uid, session_id, role, content):
    """Lưu tin nhắn kèm theo chữ ký UID của người dùng"""
    if not db: return
    try:
        # 1. Lưu nội dung chat
        db.collection("chat_logs").add({
            "uid": uid,           # <--- KHÓA BẢO MẬT
            "session_id": session_id,
            "role": role,
            "content": content,
            "timestamp": firestore.SERVER_TIMESTAMP
        })
        
        # 2. Cập nhật tên Session (chỉ khi user chat)
        if role == "user":
            # Tạo tiêu đề ngắn gọn (40 ký tự đầu)
            title = (content[:40] + "...") if len(content) > 40 else content
            db.collection("sessions").document(session_id).set({
                "uid": uid,       # <--- KHÓA BẢO MẬT
                "session_id": session_id,
                "title": title,
                "last_updated": firestore.SERVER_TIMESTAMP
            }, merge=True)
    except: pass

def load_user_sessions(uid):
    """CHỈ tải những phiên chat của đúng UID này"""
    if not db: return []
    try:
        # LỌC DỮ LIỆU: where("uid", "==", uid) -> Không bao giờ lộ tin nhắn người khác
        docs = db.collection("sessions")\
            .where("uid", "==", uid)\
            .order_by("last_updated", direction=firestore.Query.DESCENDING)\
            .stream()
        return [{"id": doc.id, **doc.to_dict()} for doc in docs]
    except: return []

def load_chat_history(session_id):
    """Tải nội dung chi tiết của một phiên chat"""
    if not db: return []
    try:
        docs = db.collection("chat_logs")\
            .where("session_id", "==", session_id)\
            .order_by("timestamp", direction=firestore.Query.ASCENDING)\
            .stream()
        return [{"role": doc.to_dict()["role"], "content": doc.to_dict()["content"]} for doc in docs]
    except: return []

# --- 6. HÀM ĐĂNG NHẬP/ĐĂNG KÝ ---
def sign_in(email, password):
    try:
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={web_api_key}"
        r = requests.post(url, json={"email": email, "password": password, "returnSecureToken": True})
        return r.json()
    except: return {"error": "Lỗi kết nối"}

def sign_up(email, password):
    try:
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={web_api_key}"
        r = requests.post(url, json={"email": email, "password": password, "returnSecureToken": True})
        return r.json()
    except: return {"error": "Lỗi kết nối"}

# --- 7. QUẢN LÝ TRẠNG THÁI ---
if "user_info" not in st.session_state:
    st.session_state.user_info = None

if "current_session_id" not in st.session_state:
    st.session_state.current_session_id = str(uuid.uuid4())

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# --- 8. GIAO DIỆN CỔNG VÀO (LOGIN) ---
if not st.session_state.user_info:
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.title("TAIMS 🎯")
        st.caption("Đăng nhập để xem lại hành trình của bạn.")
        
        tab1, tab2 = st.tabs(["Đăng Nhập", "Đăng Ký"])
        
        with tab1:
            email_in = st.text_input("Email", key="l_email")
            pass_in = st.text_input("Mật khẩu", type="password", key="l_pass")
            if st.button("Vào ngay", use_container_width=True):
                with st.spinner("..."):
                    resp = sign_in(email_in, pass_in)
                    if "localId" in resp:
                        st.session_state.user_info = {"uid": resp["localId"], "email": resp["email"]}
                        st.rerun()
                    else:
                        st.error("Sai tài khoản hoặc mật khẩu!")

        with tab2:
            email_up = st.text_input("Email", key="r_email")
            pass_up = st.text_input("Mật khẩu", type="password", key="r_pass")
            if st.button("Tạo tài khoản", use_container_width=True):
                if len(pass_up) < 6: st.warning("Mật khẩu ngắn quá!")
                else:
                    with st.spinner("..."):
                        resp = sign_up(email_up, pass_up)
                        if "localId" in resp:
                            st.session_state.user_info = {"uid": resp["localId"], "email": resp["email"]}
                            st.success("Tạo thành công!")
                            st.rerun()
                        else:
                            st.error("Email này đã tồn tại!")

# --- 9. GIAO DIỆN CHÍNH (SAU KHI VÀO NHÀ) ---
else:
    user_uid = st.session_state.user_info["uid"]
    user_email = st.session_state.user_info["email"]

    # --- SIDEBAR: LỊCH SỬ ---
    with st.sidebar:
        st.caption(f"User: {user_email}")
        
        # Nút tạo mới
        if st.button("➕ Chat Mới", type="primary", use_container_width=True):
            st.session_state.current_session_id = str(uuid.uuid4())
            st.session_state.chat_history = []
            st.rerun()
        
        st.divider()
        st.subheader("🗂️ Lịch sử")

        # Load danh sách cũ
        sessions = load_user_sessions(user_uid)
        
        if not sessions:
            st.caption("(Chưa có lịch sử)")
        
        for sess in sessions:
            # Hiển thị từng dòng lịch sử
            btn_label = f"📝 {sess.get('title', 'No title')}"
            if st.button(btn_label, key=sess['id'], use_container_width=True):
                st.session_state.current_session_id = sess['id']
                st.session_state.chat_history = load_chat_history(sess['id'])
                st.rerun()

        st.divider()
        if st.button("Đăng xuất 🚪", use_container_width=True):
            st.session_state.user_info = None
            st.session_state.chat_history = []
            st.rerun()

    # --- CHAT WINDOW ---
    st.title("TAIMS 🎯")
    
    # Hiển thị tin nhắn
    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Xử lý nhập liệu
    user_input = st.chat_input("Cùng TAIMS thiết kế lộ trình...")

    if user_input:
        # 1. User
        st.session_state.chat_history.append({"role": "user", "content": user_input})
        with st.chat_message("user"): st.markdown(user_input)
        
        # Lưu vào DB
        save_message(user_uid, st.session_state.current_session_id, "user", user_input)

        # 2. AI
        gemini_history = []
        for msg in st.session_state.chat_history:
            role = "model" if msg["role"] == "assistant" else "user"
            gemini_history.append({"role": role, "parts": [msg["content"]]})

        with st.chat_message("assistant"):
            with st.spinner("..."):
                try:
                    try:
                        model = genai.GenerativeModel("models/gemini-1.5-flash", system_instruction=TAIMS_INSTRUCTION)
                    except:
                        model = genai.GenerativeModel("gemini-pro")
                        
                    chat = model.start_chat(history=gemini_history)
                    response = chat.send_message(user_input)
                    reply = response.text
                    
                    st.markdown(reply)
                    st.session_state.chat_history.append({"role": "assistant", "content": reply})
                    
                    # Lưu AI vào DB
                    save_message(user_uid, st.session_state.current_session_id, "assistant", reply)
                    
                except Exception as e:
                    st.error(f"Lỗi: {e}")
        
        # Tải lại để cập nhật tên session bên sidebar
        st.rerun()
