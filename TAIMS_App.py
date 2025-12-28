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

TAIMS_INSTRUCTION = TAIMS_INSTRUCTION = """
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


def get_key(name):
    try:
        return st.secrets[name]
    except:
        return os.getenv(name)


api_key = get_key("GEMINI_API_KEY")
web_api_key = get_key("FIREBASE_WEB_API_KEY")

if not api_key: st.error("❌ Thiếu Gemini API Key"); st.stop()

try:
    genai.configure(api_key=api_key)
except:
    pass


# --- 3. KẾT NỐI DB ---
@st.cache_resource
def init_connection():
    try:
        if firebase_admin._apps: return firestore.client()
        if os.path.exists("service_account.json"):
            cred = credentials.Certificate("service_account.json")
            firebase_admin.initialize_app(cred)
            return firestore.client()
        if "FIREBASE" in st.secrets:
            key_dict = json.loads(st.secrets["FIREBASE"]["credentials_json"], strict=False)
            cred = credentials.Certificate(key_dict)
            firebase_admin.initialize_app(cred)
            return firestore.client()
        return None
    except:
        return None


db = init_connection()


# --- 4. HÀM TỰ ĐỘNG TÌM MODEL (FIX 404) ---
@st.cache_resource
def get_valid_model_name():
    """Hỏi Google xem tài khoản này được dùng cái gì"""
    try:
        valid_models = []
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                valid_models.append(m.name)

        # Ưu tiên tìm Flash -> Pro -> 1.5 -> 1.0
        for m in valid_models:
            if 'flash' in m.lower(): return m
        for m in valid_models:
            if 'pro' in m.lower() and '1.5' in m: return m

        # Nếu không có cái ưu tiên, lấy cái đầu tiên tìm thấy
        if valid_models: return valid_models[0]
        return "models/gemini-pro"  # Fallback cuối cùng
    except:
        return "models/gemini-pro"


# --- 5. LOGIC DỮ LIỆU ---
def save_message(uid, session_id, role, content):
    if not db: return
    try:
        db.collection("chat_logs").add({
            "uid": uid, "session_id": session_id, "role": role, "content": content,
            "timestamp": firestore.SERVER_TIMESTAMP
        })
        if role == "user":
            title = (content[:30] + "...") if len(content) > 30 else content
            db.collection("sessions").document(session_id).set({
                "uid": uid, "session_id": session_id, "title": title, "last_updated": firestore.SERVER_TIMESTAMP
            }, merge=True)
    except:
        pass


def delete_session_db(session_id):
    if not db: return
    try:
        db.collection("sessions").document(session_id).delete()
        logs = db.collection("chat_logs").where("session_id", "==", session_id).stream()
        for log in logs: log.reference.delete()
        return True
    except:
        return False


def load_user_sessions(uid):
    if not db: return []
    try:
        docs = db.collection("sessions").where("uid", "==", uid).order_by("last_updated",
                                                                          direction=firestore.Query.DESCENDING).stream()
        return [{"id": doc.id, **doc.to_dict()} for doc in docs]
    except:
        return []


def load_chat_history(session_id):
    if not db: return []
    try:
        docs = db.collection("chat_logs").where("session_id", "==", session_id).order_by("timestamp",
                                                                                         direction=firestore.Query.ASCENDING).stream()
        return [{"role": doc.to_dict()["role"], "content": doc.to_dict()["content"]} for doc in docs]
    except:
        return []


# --- 6. EXCEL LOGIC ---
def create_excel(text):
    try:
        model_name = get_valid_model_name()  # Tự động lấy tên đúng
        model = genai.GenerativeModel(model_name)
        prompt = f"Extract JSON list from text. Text: {text[:4000]}. Format: List of objects. JSON ONLY. No markdown."

        resp = model.generate_content(prompt)
        json_str = resp.text.replace("```json", "").replace("```", "").strip()
        data = json.loads(json_str)
        df = pd.DataFrame(data)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False)
        return output.getvalue()
    except:
        return None


# --- 7. AUTH ---
def auth_action(email, password, mode="signin"):
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:{'signInWithPassword' if mode == 'signin' else 'signUp'}?key={web_api_key}"
    try:
        return requests.post(url, json={"email": email, "password": password, "returnSecureToken": True}).json()
    except Exception as e:
        return {"error": str(e)}


# --- 8. UI ---
if "user_info" not in st.session_state: st.session_state.user_info = None
if "current_session_id" not in st.session_state: st.session_state.current_session_id = str(uuid.uuid4())
if "chat_history" not in st.session_state: st.session_state.chat_history = []

# MÀN HÌNH LOGIN
if not st.session_state.user_info:
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.title("TAIMS 🎯")
        st.caption("Target Action Integrated Management System")

        tab1, tab2 = st.tabs(["Đăng Nhập", "Đăng Ký"])
        with tab1:
            e = st.text_input("Email", key="l1");
            p = st.text_input("Mật khẩu", type="password", key="l2")
            if st.button("Vào Ngay", use_container_width=True):
                res = auth_action(e, p, "signin")
                if "localId" in res:
                    st.session_state.user_info = {"uid": res["localId"], "email": res["email"]}; st.rerun()
                else:
                    st.error("Sai thông tin")
        with tab2:
            e = st.text_input("Email", key="r1");
            p = st.text_input("Mật khẩu", type="password", key="r2")
            if st.button("Tạo Tài Khoản", use_container_width=True):
                res = auth_action(e, p, "signup")
                if "localId" in res:
                    st.session_state.user_info = {"uid": res["localId"], "email": res["email"]}; st.success(
                        "OK"); st.rerun()
                else:
                    st.error("Lỗi đăng ký")

# MÀN HÌNH CHÍNH
else:
    uid = st.session_state.user_info["uid"]

    with st.sidebar:
        if st.button("➕ Chat Mới", type="primary", use_container_width=True):
            st.session_state.current_session_id = str(uuid.uuid4());
            st.session_state.chat_history = [];
            st.rerun()

        st.divider()
        sessions = load_user_sessions(uid)
        for s in sessions:
            c1, c2 = st.columns([0.8, 0.2])
            with c1:
                lbl = f"📄 {s.get('title', '...')}"
                if s['id'] == st.session_state.current_session_id: lbl = f"🟢 {s.get('title', '...')}"
                if st.button(lbl, key=f"btn_{s['id']}", use_container_width=True):
                    st.session_state.current_session_id = s['id']
                    st.session_state.chat_history = load_chat_history(s['id'])
                    st.rerun()
            with c2:
                if st.button("🗑️", key=f"del_{s['id']}"):
                    delete_session_db(s['id'])
                    if s['id'] == st.session_state.current_session_id:
                        st.session_state.current_session_id = str(uuid.uuid4());
                        st.session_state.chat_history = []
                    st.rerun()

        st.divider()
        if st.button("Đăng xuất"): st.session_state.user_info = None; st.rerun()

    st.title("TAIMS 🎯")
    st.caption("Target Action Integrated Management System")

    if not st.session_state.chat_history and db:
        st.session_state.chat_history = load_chat_history(st.session_state.current_session_id)

    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg["role"] == "assistant":
                if "thứ" in msg["content"].lower() or "ngày" in msg["content"].lower():
                    k = f"xl_{hash(msg['content'])}"
                    if st.button("📥 Xuất Excel", key=k):
                        d = create_excel(msg["content"])
                        if d: st.download_button("Tải về", d, "TAIMS.xlsx", key=f"d_{k}")

    if prompt := st.chat_input("Nhập yêu cầu..."):
        st.session_state.chat_history.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        save_message(uid, st.session_state.current_session_id, "user", prompt)

        with st.chat_message("assistant"):
            with st.spinner("..."):
                try:
                    gh = []
                    for m in st.session_state.chat_history:
                        gh.append({"role": "model" if m["role"] == "assistant" else "user", "parts": [m["content"]]})

                    # QUAN TRỌNG: Tự tìm tên model đúng
                    correct_model_name = get_valid_model_name()

                    # Cấu hình retry
                    model = genai.GenerativeModel(correct_model_name, system_instruction=TAIMS_INSTRUCTION)

                    # Logic retry đơn giản (3 lần)
                    for attempt in range(3):
                        try:
                            response = model.generate_content(gh)  # Gọi thẳng, không qua chat session để dễ debug
                            reply = response.text
                            break  # Thành công thì thoát vòng lặp
                        except Exception as e:
                            if "429" in str(e):
                                time.sleep(2)  # Chờ 2s rồi thử lại
                                if attempt == 2: raise e  # Lần cuối mà vẫn lỗi thì báo
                            else:
                                raise e  # Lỗi khác thì báo luôn

                    st.markdown(reply)
                    st.session_state.chat_history.append({"role": "assistant", "content": reply})
                    save_message(uid, st.session_state.current_session_id, "assistant", reply)
                    time.sleep(0.5);
                    st.rerun()

                except Exception as e:
                    if "429" in str(e):
                        st.warning("⚠️ Server quá tải. Vui lòng thử lại sau 10s.")
                    else:
                        st.error(f"❌ Lỗi: {e}")
