import streamlit as st
import os
import json
import requests
import uuid
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

# --- 3. LOAD KEYS ---
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

# --- 5. HÀM XỬ LÝ DỮ LIỆU ---

def save_message(uid, session_id, role, content):
    """Lưu tin nhắn và cập nhật Session"""
    if not db: return
    try:
        # 1. Lưu nội dung
        db.collection("chat_logs").add({
            "uid": uid,
            "session_id": session_id,
            "role": role,
            "content": content,
            "timestamp": firestore.SERVER_TIMESTAMP
        })
        
        # 2. Cập nhật tiêu đề Session (Nếu là user)
        if role == "user":
            title = (content[:40] + "...") if len(content) > 40 else content
            # Dùng set(merge=True) để không ghi đè mất ngày tạo cũ
            db.collection("sessions").document(session_id).set({
                "uid": uid,
                "session_id": session_id,
                "title": title,
                "last_updated": firestore.SERVER_TIMESTAMP
            }, merge=True)
    except: pass

def load_user_sessions(uid):
    """Lấy danh sách chat cũ"""
    if not db: return []
    try:
        # Cần Index: uid (Asc/Desc) + last_updated (Desc)
        docs = db.collection("sessions")\
            .where("uid", "==", uid)\
            .order_by("last_updated", direction=firestore.Query.DESCENDING)\
            .stream()
        return [{"id": doc.id, **doc.to_dict()} for doc in docs]
    except Exception as e:
        # Hiển thị lỗi nếu thiếu Index để Thomas bấm vào tạo
        if "requires an index" in str(e):
            st.sidebar.error("⚠️ Cần tạo Index cho Database!")
            # Trích xuất link tạo index từ thông báo lỗi
            try:
                link = str(e).split("https://")[1].split(" ")[0]
                st.sidebar.link_button("👉 Bấm vào đây để sửa lỗi DB", f"https://{link}")
            except: pass
        return []

def load_chat_history(session_id):
    """Lấy nội dung chat của 1 phiên"""
    if not db: return []
    try:
        # Cần Index: session_id (Asc) + timestamp (Asc)
        docs = db.collection("chat_logs")\
            .where("session_id", "==", session_id)\
            .order_by("timestamp", direction=firestore.Query.ASCENDING)\
            .stream()
        return [{"role": doc.to_dict()["role"], "content": doc.to_dict()["content"]} for doc in docs]
    except Exception as e:
        return []

# --- 6. AUTH ---
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

# --- 7. SESSION STATE ---
if "user_info" not in st.session_state:
    st.session_state.user_info = None

if "current_session_id" not in st.session_state:
    st.session_state.current_session_id = str(uuid.uuid4())

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# --- 8. GIAO DIỆN LOGIN ---
if not st.session_state.user_info:
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.title("TAIMS 🎯")
        st.caption("Đăng nhập để xem lại hành trình.")
        
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
                    else: st.error("Sai thông tin!")
        with tab2:
            email_up = st.text_input("Email", key="r_email")
            pass_up = st.text_input("Mật khẩu", type="password", key="r_pass")
            if st.button("Tạo tài khoản", use_container_width=True):
                if len(pass_up) < 6: st.warning("Mật khẩu ngắn!")
                else:
                    with st.spinner("..."):
                        resp = sign_up(email_up, pass_up)
                        if "localId" in resp:
                            st.session_state.user_info = {"uid": resp["localId"], "email": resp["email"]}
                            st.success("OK!"); st.rerun()
                        else: st.error("Email đã tồn tại!")

# --- 9. GIAO DIỆN CHÍNH ---
else:
    user_uid = st.session_state.user_info["uid"]
    user_email = st.session_state.user_info["email"]

    # SIDEBAR
    with st.sidebar:
        st.caption(f"User: {user_email}")
        
        if st.button("➕ Chat Mới", type="primary", use_container_width=True):
            st.session_state.current_session_id = str(uuid.uuid4())
            st.session_state.chat_history = []
            st.rerun()
        
        st.divider()
        st.subheader("🗂️ Lịch sử")

        # Load Sessions
        sessions = load_user_sessions(user_uid)
        
        if not sessions:
            st.caption("(Chưa có lịch sử mới)")
        
        for sess in sessions:
            title = sess.get('title', 'Không tiêu đề')
            # Nếu đang chọn session này thì làm nổi bật
            icon = "🟢" if sess['id'] == st.session_state.current_session_id else "📝"
            
            if st.button(f"{icon} {title}", key=sess['id'], use_container_width=True):
                st.session_state.current_session_id = sess['id']
                st.session_state.chat_history = load_chat_history(sess['id'])
                st.rerun()

        st.divider()
        if st.button("Đăng xuất 🚪", use_container_width=True):
            st.session_state.user_info = None
            st.session_state.chat_history = []
            st.rerun()

    # MAIN CHAT
    st.title("TAIMS 🎯")

    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    user_input = st.chat_input("Cùng TAIMS thiết kế lộ trình...")

    if user_input:
        # 1. User
        st.session_state.chat_history.append({"role": "user", "content": user_input})
        with st.chat_message("user"): st.markdown(user_input)
        
        save_message(user_uid, st.session_state.current_session_id, "user", user_input)

        # 2. AI
        # Chuyển đổi lịch sử cho đúng format Gemini
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
                    reply = chat.send_message(user_input).text
                    st.markdown(reply)
                    
                    st.session_state.chat_history.append({"role": "assistant", "content": reply})
                    save_message(user_uid, st.session_state.current_session_id, "assistant", reply)
                    
                except Exception as e:
                    st.error(f"Lỗi: {e}")
        st.rerun()
