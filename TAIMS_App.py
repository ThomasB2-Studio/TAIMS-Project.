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

# --- 2. CẤU HÌNH NHÂN CÁCH AI ---
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

# --- 5. HÀM EXCEL THÔNG MINH (ĐÃ NÂNG CẤP CHO SINH VIÊN) ---
def generate_excel_from_text(text):
    """
    AI phụ trách việc chuyển đổi văn bản hỗn độn thành Excel chuẩn.
    Đã tối ưu cho Thời Khóa Biểu Đại Học.
    """
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        # Prompt này cực quan trọng: Dạy AI cách nhặt hạt sạn ra khỏi gạo
        prompt = f"""
        Bạn là một công cụ chuyển đổi dữ liệu (Data Parser).
        Nhiệm vụ: Phân tích đoạn văn bản lộn xộn dưới đây và trích xuất thành danh sách JSON phẳng để làm Excel.
        
        Văn bản đầu vào: 
        {text}
        
        YÊU CẦU:
        1. Nếu đây là Thời Khóa Biểu (có Thứ, Tiết, Môn, Phòng...):
           - Hãy chuẩn hóa cột: "Thứ", "Tiết", "Môn Học", "Phòng", "Giảng Viên", "Ghi Chú".
           - Nếu một môn học có nhiều dòng (nhiều tuần), hãy gộp lại hoặc lấy thông tin quan trọng nhất (lịch học hằng tuần).
        
        2. Nếu đây là To-Do List thường:
           - Cột: "Ngày", "Giờ", "Công Việc", "Trạng Thái".

        OUTPUT MONG MUỐN (Chỉ trả về JSON list, không markdown):
        [
            {{"Thứ": "7", "Tiết": "8-9", "Môn Học": "Pháp luật đại cương", "Phòng": "F303(LD)", "Giảng Viên": "Lê Thị Phương Trang"}},
            ...
        ]
        """
        response = model.generate_content(prompt)
        # Làm sạch chuỗi JSON (đôi khi AI thêm ```json vào đầu)
        json_str = response.text.strip()
        if "```json" in json_str:
            json_str = json_str.split("```json")[1].split("```")[0]
        elif "```" in json_str:
            json_str = json_str.replace("```", "")
            
        data = json.loads(json_str)
        df = pd.DataFrame(data)
        
        # Tạo file Excel
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            sheet_name = 'Thoi_Khoa_Bieu'
            df.to_excel(writer, index=False, sheet_name=sheet_name)
            
            # Làm đẹp cột (Auto-fit columns)
            worksheet = writer.sheets[sheet_name]
            for i, col in enumerate(df.columns):
                max_len = max(
                    df[col].astype(str).map(len).max(),
                    len(str(col))
                ) + 2
                worksheet.set_column(i, i, max_len)
                
        return output.getvalue()
    except Exception as e:
        return None

# --- 6. LOGIC DỮ LIỆU ---
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
    except: return []

def load_chat_history(session_id):
    if not db: return []
    try:
        docs = db.collection("chat_logs").where("session_id", "==", session_id).order_by("timestamp", direction=firestore.Query.ASCENDING).stream()
        return [{"role": doc.to_dict()["role"], "content": doc.to_dict()["content"]} for doc in docs]
    except: return []

# --- 7. AUTH ---
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

def call_gemini_safe(history, user_input):
    models_to_try = ["gemini-1.5-flash", "gemini-pro"]
    for model_name in models_to_try:
        try:
            model = genai.GenerativeModel(model_name, system_instruction=TAIMS_INSTRUCTION)
            chat = model.start_chat(history=history)
            response = chat.send_message(user_input)
            return response.text
        except: continue
    return "Lỗi kết nối AI."

# --- 8. GIAO DIỆN ---
if "user_info" not in st.session_state: st.session_state.user_info = None
if "current_session_id" not in st.session_state: st.session_state.current_session_id = str(uuid.uuid4())
if "chat_history" not in st.session_state: st.session_state.chat_history = []

if not st.session_state.user_info:
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.title("TAIMS 🎯")
        st.caption("Sinh viên năm cuối & Du học Master.")
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
    uid = st.session_state.user_info["uid"]
    with st.sidebar:
        if st.button("➕ Chat Mới"): st.session_state.current_session_id = str(uuid.uuid4()); st.session_state.chat_history = []; st.rerun()
        st.divider()
        for s in load_user_sessions(uid):
            if st.button(f"📅 {s.get('title','...')}", key=s['id']): 
                st.session_state.current_session_id = s['id']
                st.session_state.chat_history = load_chat_history(s['id'])
                st.rerun()
        st.divider()
        if st.button("Logout"): st.session_state.user_info = None; st.rerun()

    st.title("TAIMS 🎯")
    
    if not st.session_state.chat_history and db:
        st.session_state.chat_history = load_chat_history(st.session_state.current_session_id)

    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            
            # --- TÍNH NĂNG TẢI EXCEL ---
            if msg["role"] == "assistant":
                # Nút download sẽ hiện ra khi AI phát hiện dữ liệu dạng bảng hoặc danh sách
                if "thứ" in msg["content"].lower() or "tiết" in msg["content"].lower() or "ngày" in msg["content"].lower():
                    xl_key = f"xl_{hash(msg['content'])}"
                    if st.button("📥 Xuất file Excel", key=xl_key):
                        with st.spinner("Đang xử lý dữ liệu hỗn độn..."):
                            excel_data = generate_excel_from_text(msg["content"])
                            if excel_data:
                                st.download_button(
                                    label="👉 Tải về TKB.xlsx",
                                    data=excel_data,
                                    file_name="Thoi_Khoa_Bieu_TAIMS.xlsx",
                                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                    key=f"dl_{xl_key}"
                                )
                
                tasks = re.findall(r'[-*]\s+(.*)', msg["content"])
                if tasks and len(tasks) > 2:
                    with st.expander("✅ Checklist nhanh"):
                        for i, task in enumerate(tasks): st.checkbox(task, key=f"c_{hash(msg['content'])}_{i}")

    if prompt := st.chat_input("Dán thời khóa biểu vào đây..."):
        st.session_state.chat_history.append({"role": "user", "content": prompt})
        with st.chat_message("user"): st.markdown(prompt)
        save_message(uid, st.session_state.current_session_id, "user", prompt)

        with st.chat_message("assistant"):
            with st.spinner("TAIMS đang đọc lịch..."):
                try:
                    gh = [{"role": "model" if m["role"]=="assistant" else "user", "parts": [m["content"]]} for m in st.session_state.chat_history]
                    reply = call_gemini_safe(gh, prompt)
                    st.markdown(reply)
                    st.session_state.chat_history.append({"role": "assistant", "content": reply})
                    save_message(uid, st.session_state.current_session_id, "assistant", reply)
                    time.sleep(0.5); st.rerun()
                except Exception as e: st.error(f"Lỗi: {e}")
