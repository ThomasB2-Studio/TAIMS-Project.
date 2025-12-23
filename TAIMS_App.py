import streamlit as st
import os
import json
import uuid
from dotenv import load_dotenv
import google.generativeai as genai
import firebase_admin
from firebase_admin import credentials, firestore

# --- 1. CẤU HÌNH TRANG ---
st.set_page_config(page_title="TAIMS", page_icon="🎯", layout="wide")

# --- 2. CẤU HÌNH NHÂN CÁCH AI ---
TAIMS_INSTRUCTION = """
Bạn là TAIMS - Trợ lý AI chuyên về Quản lý Thời gian và Hiệu suất (Time & Performance Management).

Nhiệm vụ cốt lõi:
1. Biến mục tiêu mơ hồ thành Kế hoạch hành động (Action Plan) cụ thể.
2. Chia nhỏ các đầu việc lớn (Big Goals) thành các bước nhỏ dễ thực hiện (Micro-tasks).
3. Giữ vai trò một người đồng hành tỉnh táo, logic và thực tế.

Nguyên tắc giao tiếp:
- Tên của bạn là TAIMS.
- Không nói đạo lý sáo rỗng. Tập trung vào giải pháp "làm thế nào" (How-to).
- Trả lời ngắn gọn, súc tích, sử dụng gạch đầu dòng (bullet points) để dễ đọc.
- Nếu người dùng đưa ra mục tiêu phi thực tế, hãy phản biện nhẹ nhàng và đề xuất hướng đi khả thi hơn.
- Luôn hỏi ngược lại để làm rõ vấn đề nếu thông tin chưa đủ.

Tuyệt đối không tự nhận là con người. Bạn là một công cụ hỗ trợ tư duy tối ưu.
"""

# --- 3. KẾT NỐI API KEY ---
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    if "GEMINI_API_KEY" in st.secrets:
        api_key = st.secrets["GEMINI_API_KEY"]
    else:
        st.error("❌ Thiếu Gemini API Key.")
        st.stop()

try:
    genai.configure(api_key=api_key)
except Exception as e:
    st.error(f"Lỗi Key: {e}")
    st.stop()


# --- 4. KẾT NỐI FIREBASE ---
@st.cache_resource
def init_connection():
    try:
        if firebase_admin._apps:
            return firestore.client()

        if os.path.exists("service_account.json"):
            cred = credentials.Certificate("service_account.json")
            firebase_admin.initialize_app(cred)
            return firestore.client()

        if "FIREBASE" in st.secrets:
            key_content = st.secrets["FIREBASE"]["credentials_json"]
            key_dict = json.loads(key_content, strict=False)
            cred = credentials.Certificate(key_dict)
            firebase_admin.initialize_app(cred)
            return firestore.client()
        return None
    except Exception as e:
        return None


db = init_connection()

# --- 5. KHỞI TẠO SESSION ID ---
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# --- THANH BÊN (SIDEBAR) ---
with st.sidebar:
    st.header("🧠 TAIMS System")
    st.caption(f"ID Phiên: {st.session_state.session_id[:8]}...")

    if db:
        st.success("✅ Database: Online")
    else:
        st.warning("⚠️ Database: Offline")

    if st.button("🗑️ Reset & New Session"):
        st.session_state.chat_history = []
        st.session_state.session_id = str(uuid.uuid4())
        st.rerun()

    st.divider()

    # --- NHẬT KÝ RIÊNG TƯ ---
    st.subheader("🗂️ Nhật ký phiên này")
    if db:
        try:
            docs = db.collection("chat_logs") \
                .where("session_id", "==", st.session_state.session_id) \
                .where("role", "==", "user") \
                .order_by("timestamp", direction=firestore.Query.DESCENDING) \
                .limit(10) \
                .stream()

            found_logs = False
            for doc in docs:
                found_logs = True
                data = doc.to_dict()
                content = data.get("content", "")
                preview = (content[:40] + '...') if len(content) > 40 else content
                st.caption(f"📝 {preview}")

            if not found_logs:
                st.caption("(Trống)")

        except Exception as e:
            st.caption("Đang đồng bộ...")
    else:
        st.caption("Kết nối DB để xem lịch sử.")

    st.divider()

    try:
        models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        default_idx = models.index("models/gemini-1.5-flash") if "models/gemini-1.5-flash" in models else 0
        model_name = st.selectbox("Model:", models, index=default_idx)
    except:
        model_name = "models/gemini-1.5-flash"

# --- MAIN PAGE ---
st.title("TAIMS 🎯")
st.caption("Target Action Integrated Management System")

for msg in st.session_state.chat_history:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Xử lý Chat - CÂU MỜI GỌI ĐÃ ĐƯỢC CẬP NHẬT
user_input = st.chat_input("Cùng TAIMS thiết kế lộ trình của riêng bạn...")

if user_input:
    # 1. User
    st.session_state.chat_history.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    if db:
        try:
            db.collection("chat_logs").add({
                "session_id": st.session_state.session_id,
                "role": "user",
                "content": user_input,
                "timestamp": firestore.SERVER_TIMESTAMP
            })
        except:
            pass

    # 2. AI
    gemini_history = []
    for msg in st.session_state.chat_history:
        role = "model" if msg["role"] == "assistant" else "user"
        gemini_history.append({"role": role, "parts": [msg["content"]]})

    with st.chat_message("assistant"):
        with st.spinner("TAIMS đang thiết kế..."):
            try:
                model = genai.GenerativeModel(
                    model_name=model_name,
                    system_instruction=TAIMS_INSTRUCTION
                )

                chat = model.start_chat(history=gemini_history)
                response = chat.send_message(user_input)
                reply = response.text

                st.markdown(reply)

                st.session_state.chat_history.append({"role": "assistant", "content": reply})

                if db:
                    try:
                        db.collection("chat_logs").add({
                            "session_id": st.session_state.session_id,
                            "role": "assistant",
                            "content": reply,
                            "timestamp": firestore.SERVER_TIMESTAMP
                        })
                    except:
                        pass
            except Exception as e:
                st.error(f"Lỗi hệ thống: {e}")

    st.rerun()
