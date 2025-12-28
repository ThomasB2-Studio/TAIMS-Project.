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

# --- 2. CẤU HÌNH HỆ THỐNG ---
TAIMS_INSTRUCTION = """
Bạn là TAIMS - Trợ lý AI chuyên về Quản lý Thời gian và Hiệu suất.
Nhiệm vụ: Biến mục tiêu thành Kế hoạch hành động.
Nguyên tắc:
- Tên là TAIMS.
- Trả lời ngắn gọn, tập trung vào giải pháp (How-to).
- Không nói đạo lý sáo rỗng.
Tuyệt đối không tự nhận là con người.
"""

# --- 3. LOAD KEYS (ĐOẠN NÀY ĐÃ ĐƯỢC GIA CỐ CHỐNG LỖI) ---
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
web_api_key = os.getenv("FIREBASE_WEB_API_KEY")


# Hàm lấy secrets an toàn (Chống crash khi chạy local)
def get_secret(key_name):
    try:
        return st.secrets[key_name]
    except:
        return None


# Nếu không tìm thấy trong .env thì mới tìm trong secrets
if not api_key:
    api_key = get_secret("GEMINI_API_KEY")

if not web_api_key:
    web_api_key = get_secret("FIREBASE_WEB_API_KEY")

# Kiểm tra lần cuối
if not api_key: st.error("❌ Thiếu Gemini API Key"); st.stop()
if not web_api_key: st.warning("⚠️ Thiếu Web API Key (Đăng nhập có thể lỗi)")

# Cấu hình Gemini
try:
    genai.configure(api_key=api_key)
except:
    pass


# --- 4. KẾT NỐI DATABASE ---
@st.cache_resource
def init_connection():
    try:
        if firebase_admin._apps: return firestore.client()

        # Local
        if os.path.exists("service_account.json"):
            cred = credentials.Certificate("service_account.json")
            firebase_admin.initialize_app(cred)
            return firestore.client()

        # Cloud (Secrets)
        # Dùng hàm get_secret để lấy chuỗi JSON an toàn
        try:
            if "FIREBASE" in st.secrets:
                key_content = st.secrets["FIREBASE"]["credentials_json"]
                key_dict = json.loads(key_content, strict=False)
                cred = credentials.Certificate(key_dict)
                firebase_admin.initialize_app(cred)
                return firestore.client()
        except:
            return None

        return None
    except:
        return None


db = init_connection()


# --- 5. HÀM XỬ LÝ ĐĂNG NHẬP (AUTH FUNCTIONS) ---
def sign_in_with_email_password(email, password):
    try:
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={web_api_key}"
        payload = {"email": email, "password": password, "returnSecureToken": True}
        r = requests.post(url, json=payload)
        return r.json()
    except:
        return {"error": "Lỗi kết nối"}


def sign_up_with_email_password(email, password):
    try:
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={web_api_key}"
        payload = {"email": email, "password": password, "returnSecureToken": True}
        r = requests.post(url, json=payload)
        return r.json()
    except:
        return {"error": "Lỗi kết nối"}


# --- 6. QUẢN LÝ TRẠNG THÁI (SESSION) ---
if "user_info" not in st.session_state:
    st.session_state.user_info = None

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# --- 7. GIAO DIỆN: CỔNG ĐĂNG NHẬP ---
if not st.session_state.user_info:
    st.title("TAIMS 🎯")
    st.caption("Đăng nhập để tiếp tục hành trình.")

    tab1, tab2 = st.tabs(["Đăng Nhập", "Đăng Ký Mới"])

    with tab1:
        email_in = st.text_input("Email", key="login_email")
        pass_in = st.text_input("Mật khẩu", type="password", key="login_pass")
        if st.button("Vào ngay", type="primary"):
            with st.spinner("Đang kiểm tra vé..."):
                resp = sign_in_with_email_password(email_in, pass_in)
                if "localId" in resp:
                    st.session_state.user_info = {
                        "uid": resp["localId"],
                        "email": resp["email"]
                    }
                    st.success("Chào mừng trở lại!")
                    st.rerun()
                else:
                    err_msg = resp.get("error", {}).get("message", str(resp))
                    if "INVALID_PASSWORD" in err_msg:
                        st.error("Sai mật khẩu rồi!")
                    elif "EMAIL_NOT_FOUND" in err_msg:
                        st.error("Email này chưa đăng ký.")
                    else:
                        st.error(f"Lỗi: {err_msg}")

    with tab2:
        email_up = st.text_input("Email đăng ký", key="reg_email")
        pass_up = st.text_input("Mật khẩu mới", type="password", key="reg_pass")
        if st.button("Tạo tài khoản"):
            if len(pass_up) < 6:
                st.warning("Mật khẩu phải trên 6 ký tự nhé.")
            else:
                with st.spinner("Đang tạo hồ sơ..."):
                    resp = sign_up_with_email_password(email_up, pass_up)
                    if "localId" in resp:
                        st.session_state.user_info = {
                            "uid": resp["localId"],
                            "email": resp["email"]
                        }
                        st.success("Tạo thành công! Đang vào...")
                        st.rerun()
                    else:
                        err_msg = resp.get("error", {}).get("message", str(resp))
                        if "EMAIL_EXISTS" in err_msg:
                            st.error("Email này đã có người dùng.")
                        else:
                            st.error(f"Lỗi: {err_msg}")

# --- 8. GIAO DIỆN: CHÍNH (SAU KHI ĐĂNG NHẬP) ---
else:
    user_uid = st.session_state.user_info["uid"]
    user_email = st.session_state.user_info["email"]

    with st.sidebar:
        st.header("🧠 TAIMS System")
        st.info(f"User: {user_email}")

        if st.button("Đăng xuất 🚪"):
            st.session_state.user_info = None
            st.session_state.chat_history = []
            st.rerun()

        st.divider()
        st.subheader("🗂️ Lịch sử của bạn")

        if db:
            try:
                docs = db.collection("chat_logs") \
                    .where("uid", "==", user_uid) \
                    .where("role", "==", "user") \
                    .order_by("timestamp", direction=firestore.Query.DESCENDING) \
                    .limit(10).stream()

                found = False
                for doc in docs:
                    found = True
                    data = doc.to_dict()
                    content = data.get("content", "")
                    st.caption(f"📝 {content[:30]}...")
                if not found: st.caption("(Trống)")
            except:
                st.caption("(Đang tạo index...)")

        try:
            models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
            idx = models.index("models/gemini-1.5-flash") if "models/gemini-1.5-flash" in models else 0
            model_name = st.selectbox("Model:", models, index=idx)
        except:
            model_name = "models/gemini-1.5-flash"

    st.title("TAIMS 🎯")
    st.caption("Thiết kế lộ trình riêng cho bạn.")

    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    user_input = st.chat_input("Cùng TAIMS thiết kế lộ trình...")

    if user_input:
        st.session_state.chat_history.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)

        if db:
            try:
                db.collection("chat_logs").add({
                    "uid": user_uid,
                    "email": user_email,
                    "role": "user",
                    "content": user_input,
                    "timestamp": firestore.SERVER_TIMESTAMP
                })
            except:
                pass

        gemini_history = []
        for msg in st.session_state.chat_history:
            role = "model" if msg["role"] == "assistant" else "user"
            gemini_history.append({"role": role, "parts": [msg["content"]]})

        with st.chat_message("assistant"):
            with st.spinner("..."):
                try:
                    model = genai.GenerativeModel(model_name=model_name, system_instruction=TAIMS_INSTRUCTION)
                    chat = model.start_chat(history=gemini_history)
                    reply = chat.send_message(user_input).text
                    st.markdown(reply)

                    st.session_state.chat_history.append({"role": "assistant", "content": reply})

                    if db:
                        try:
                            db.collection("chat_logs").add({
                                "uid": user_uid,
                                "role": "assistant",
                                "content": reply,
                                "timestamp": firestore.SERVER_TIMESTAMP
                            })
                        except:
                            pass
                except Exception as e:
                    st.error(f"Lỗi: {e}")
