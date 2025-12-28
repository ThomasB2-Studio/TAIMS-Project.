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

# --- 2. NÃO BỘ CHUYÊN GIA LẬP KẾ HOẠCH ---
TAIMS_INSTRUCTION = """
IDENTITY:
Bạn là TAIMS - Chuyên gia tối ưu hóa hiệu suất và lập lịch trình (Scheduler).

NHIỆM VỤ:
1. Tạo TO-DO LIST chi tiết: Chia nhỏ việc cần làm.
2. Lập LỊCH TRÌNH 7 NGÀY (Weekly Plan): Phân bổ thời gian hợp lý cho học tập/công việc.

QUY TẮC TRẢ LỜI:
- Luôn dùng định dạng Markdown.
- Với danh sách việc cần làm, hãy dùng gạch đầu dòng "- [ ] Công việc...".
- Với lịch trình, hãy trình bày rõ ràng từng ngày (Thứ 2, Thứ 3...).
- Giọng văn: Thực tế, ngắn gọn, thúc giục hành động.

VÍ DỤ OUTPUT MONG MUỐN:
"Đây là lịch trình tuần này cho bạn:
- [ ] Thứ 2: Học Từ vựng (2h) - Sáng
- [ ] Thứ 3: Luyện nghe IELTS (1h) - Chiều
..."
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

# --- 4. KẾT NỐI DB ---
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

# --- 5. DATA LOGIC & EXCEL ENGINE ---
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
    except: return [] # Bỏ qua lỗi index để UI sạch sẽ

def load_chat_history(session_id):
    if not db: return []
    try:
        docs = db.collection("chat_logs").where("session_id", "==", session_id).order_by("timestamp", direction=firestore.Query.ASCENDING).stream()
        return [{"role": doc.to_dict()["role"], "content": doc.to_dict()["content"]} for doc in docs]
    except: return []

# --- HÀM TẠO EXCEL TỪ TEXT AI ---
def generate_excel_from_text(text):
    """Dùng một AI phụ để chuyển văn bản thành JSON rồi sang Excel"""
    try:
        # Gọi Gemini lần 2 để ép kiểu dữ liệu sang JSON (cho máy đọc)
        model = genai.GenerativeModel('gemini-1.5-flash')
        prompt = f"""
        Trích xuất lịch trình hoặc danh sách công việc từ văn bản sau thành định dạng JSON.
        Văn bản: {text}
        
        Output mong muốn (JSON list):
        [
            {{"Ngày": "Thứ 2", "Giờ": "Sáng", "Công_Việc": "Học bài", "Trạng_Thái": "Chưa xong"}},
            ...
        ]
        Chỉ trả về JSON thuần, không có markdown.
        """
        response = model.generate_content(prompt)
        json_str = response.text.strip().replace("```json", "").replace("```", "")
        
        data = json.loads(json_str)
        df = pd.DataFrame(data)
        
        # Tạo file Excel trong bộ nhớ
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='Lich_Trinh_TAIMS')
            # Auto-adjust columns width (làm đẹp cột)
            worksheet = writer.sheets['Lich_Trinh_TAIMS']
            for i, col in enumerate(df.columns):
                column_len = max(df[col].astype(str).map(len).max(), len(col)) + 2
                worksheet.set_column(i, i, column_len)
                
        return output.getvalue()
    except Exception as e:
        return None

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

# --- 7. AI SAFETY ---
def call_gemini_safe(history, user_input):
    models_to_try = ["gemini-1.5-flash", "gemini-pro"]
    for model_name in models_to_try:
        try:
            model = genai.GenerativeModel(model_name, system_instruction=TAIMS_INSTRUCTION)
            chat = model.start_chat(history=history)
            response = chat.send_message(user_input)
            return response.text
        except: continue
    return "TAIMS đang quá tải, hãy thử lại sau giây lát."

# --- 8. GIAO DIỆN ---
if "user_info" not in st.session_state: st.session_state.user_info = None
if "current_session_id" not in st.session_state: st.session_state.current_session_id = str(uuid.uuid4())
if "chat_history" not in st.session_state: st.session_state.chat_history = []

if not st.session_state.user_info:
    # LOGIN
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.title("TAIMS 🎯")
        st.caption("Quản lý thời gian - Tối ưu hiệu suất.")
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
    # MAIN APP
    uid = st.session_state.user_info["uid"]
    
    with st.sidebar:
        if st.button("➕ Kế Hoạch Mới"): st.session_state.current_session_id = str(uuid.uuid4()); st.session_state.chat_history = []; st.rerun()
        st.divider()
        sessions = load_user_sessions(uid)
        for s in sessions:
            if st.button(f"📅 {s.get('title','...')}", key=s['id']): 
                st.session_state.current_session_id = s['id']
                st.session_state.chat_history = load_chat_history(s['id'])
                st.rerun()
        st.divider()
        if st.button("Logout"): st.session_state.user_info = None; st.rerun()

    st.title("TAIMS 🎯")
    
    if not st.session_state.chat_history and db:
        st.session_state.chat_history = load_chat_history(st.session_state.current_session_id)

    # --- HIỂN THỊ CHAT ---
    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            
            # TÍNH NĂNG ĐẶC BIỆT: NẾU LÀ AI VÀ CÓ CHỨA DANH SÁCH VIỆC
            if msg["role"] == "assistant":
                # 1. Tạo File Excel
                if "thứ" in msg["content"].lower() or "day" in msg["content"].lower():
                    # Dùng key duy nhất dựa trên độ dài content để tránh trùng
                    xl_key = f"xl_{hash(msg['content'])}"
                    if st.button("📥 Tải lịch trình này (Excel)", key=xl_key):
                        with st.spinner("Đang tạo file Excel..."):
                            excel_data = generate_excel_from_text(msg["content"])
                            if excel_data:
                                st.download_button(
                                    label="👉 Bấm để tải xuống ngay",
                                    data=excel_data,
                                    file_name="Lich_Trinh_TAIMS.xlsx",
                                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                    key=f"dl_{xl_key}"
                                )
                
                # 2. Trích xuất Checkbox (To-Do List tương tác)
                # Tìm các dòng bắt đầu bằng - [ ] hoặc * [ ] hoặc - 
                tasks = re.findall(r'[-*]\s+(.*)', msg["content"])
                if tasks and len(tasks) > 2:
                    with st.expander("✅ To-Do List tương tác"):
                        for i, task in enumerate(tasks):
                            st.checkbox(task, key=f"chk_{hash(msg['content'])}_{i}")

    # --- INPUT ---
    if prompt := st.chat_input("VD: Lập lịch học IELTS trong 1 tuần..."):
        st.session_state.chat_history.append({"role": "user", "content": prompt})
        with st.chat_message("user"): st.markdown(prompt)
        save_message(uid, st.session_state.current_session_id, "user", prompt)

        with st.chat_message("assistant"):
            with st.spinner("TAIMS đang thiết kế..."):
                try:
                    history_for_ai = []
                    for m in st.session_state.chat_history:
                        role = "model" if m["role"]=="assistant" else "user"
                        history_for_ai.append({"role": role, "parts": [m["content"]]})
                    
                    reply = call_gemini_safe(history_for_ai, prompt)
                    
                    st.markdown(reply)
                    st.session_state.chat_history.append({"role": "assistant", "content": reply})
                    save_message(uid, st.session_state.current_session_id, "assistant", reply)
                    time.sleep(0.5)
                    st.rerun()
                except Exception as e:
                    st.error(f"Lỗi: {e}")
