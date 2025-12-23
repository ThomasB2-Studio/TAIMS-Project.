import streamlit as st
import os
from dotenv import load_dotenv
import google.generativeai as genai

# --- 1. CẤU HÌNH TRANG ---
st.set_page_config(page_title="TAIMS", page_icon="🎯", layout="wide")

# --- 2. KẾT NỐI & KIỂM TRA MODEL ---
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

st.title("TAIMS 🎯 - Phiên bản Sửa Lỗi")

# Kiểm tra Key
if not api_key:
    st.error("❌ Chưa tìm thấy API Key trong file .env")
    st.stop()

# Cấu hình AI
try:
    genai.configure(api_key=api_key)
except Exception as e:
    st.error(f"❌ Lỗi cấu hình Key: {e}")
    st.stop()

# --- 3. TỰ ĐỘNG TÌM MODEL (DEBUG) ---
# Phần này giúp Thomas biết chính xác Key của mình dùng được model nào
with st.sidebar:
    st.header("🔧 Thông tin Kỹ thuật")
    st.write("Đang kiểm tra các Model khả dụng...")
    try:
        available_models = []
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                available_models.append(m.name)

        if available_models:
            st.success(f"Tìm thấy {len(available_models)} model!")
            # Cho phép chọn model để tránh lỗi 404
            selected_model = st.selectbox("Chọn Model:", available_models, index=0)
        else:
            st.error("Không tìm thấy Model nào hỗ trợ tạo nội dung.")
            st.stop()

    except Exception as e:
        st.error(f"Lỗi khi liệt kê model: {e}")
        selected_model = "models/gemini-1.5-flash"  # Fallback

# --- 4. KHỞI TẠO BỘ NHỚ (SESSION STATE) ---
# Đây là đoạn bạn đã phát hiện lỗi, tôi đã sửa lại đúng cú pháp
if "tasks" not in st.session_state:
    st.session_state.tasks = []  # ✅ ĐÃ SỬA: Gán bằng danh sách rỗng

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# --- 5. GIAO DIỆN CHÍNH ---
st.caption(f"Đang sử dụng bộ não: `{selected_model}`")

# Hiển thị lịch sử chat
for message in st.session_state.chat_history:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Ô nhập liệu
user_input = st.chat_input("Nhập mục tiêu của bạn (Ví dụ: Học tiếng Pháp trong 2 tháng)...")

if user_input:
    # 1. Hiện câu hỏi của user
    st.session_state.chat_history.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    # 2. AI xử lý
    with st.chat_message("assistant"):
        with st.spinner("Thomas đợi chút, AI đang suy nghĩ..."):
            try:
                # Khởi tạo model từ cái tên đã chọn ở Sidebar
                model = genai.GenerativeModel(selected_model)

                # Gửi lệnh
                response = model.generate_content(
                    f"Hãy đóng vai trợ lý TAIMS. Giúp tôi chia nhỏ mục tiêu này thành 3 bước cụ thể kèm thời gian: {user_input}")
                ai_reply = response.text

                # Hiện câu trả lời
                st.markdown(ai_reply)

                # Lưu vào lịch sử
                st.session_state.chat_history.append({"role": "assistant", "content": ai_reply})

                # (Tạm thời giả lập tasks để test lỗi session_state)
                st.session_state.tasks = ["Đã nhận kế hoạch từ AI"]

            except Exception as e:
                st.error(f"❌ Vẫn còn lỗi: {e}")
                st.info("Mẹo: Hãy thử chọn Model khác ở thanh bên trái (Sidebar)!")