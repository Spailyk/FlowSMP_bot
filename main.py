import os
import logging
import sqlite3
import asyncio
import threading
from datetime import datetime
from flask import Flask, request, jsonify
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ==================== НАСТРОЙКИ ====================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not set in environment variables")

ADMIN_ID = 7019179888  # Ваш ID

REPORTS_MEDIA_DIR = "reports_media"
os.makedirs(REPORTS_MEDIA_DIR, exist_ok=True)

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Flask приложение
app = Flask(__name__)

# ==================== БАЗА ДАННЫХ ====================
def init_db():
    conn = sqlite3.connect('bot.db')
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            user_name TEXT,
            username TEXT,
            nickname TEXT,
            age TEXT,
            reason TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            user_name TEXT,
            username TEXT,
            offender_nick TEXT,
            reason TEXT,
            evidence TEXT,
            evidence_type TEXT,
            time TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# ==================== УПРОЩЁННЫЕ ФУНКЦИИ БД ====================
def add_request(user_id, user_name, username, nickname, age, reason):
    conn = sqlite3.connect('bot.db')
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO requests (user_id, user_name, username, nickname, age, reason)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (user_id, user_name, username, nickname, age, reason))
    request_id = cur.lastrowid
    conn.commit()
    conn.close()
    return request_id

def update_request_status(request_id, status):
    conn = sqlite3.connect('bot.db')
    cur = conn.cursor()
    cur.execute('UPDATE requests SET status = ? WHERE id = ?', (status, request_id))
    conn.commit()
    conn.close()

def add_report(user_id, user_name, username, offender_nick, reason, evidence, evidence_type, time):
    conn = sqlite3.connect('bot.db')
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO reports (user_id, user_name, username, offender_nick, reason, evidence, evidence_type, time)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, user_name, username, offender_nick, reason, evidence, evidence_type, time))
    report_id = cur.lastrowid
    conn.commit()
    conn.close()
    return report_id

def update_report_status(report_id, status):
    conn = sqlite3.connect('bot.db')
    cur = conn.cursor()
    cur.execute('UPDATE reports SET status = ? WHERE id = ?', (status, report_id))
    conn.commit()
    conn.close()

# ==================== КЛАВИАТУРЫ ====================
def get_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⚡️Старт")],
            [KeyboardButton(text="ℹ️ Информация"), KeyboardButton(text="📝 Заявка")],
            [KeyboardButton(text="🆘 Помощь"), KeyboardButton(text="⚠️ Репорт")]
        ],
        resize_keyboard=True
    )

def get_cancel_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ ОТМЕНА")]],
        resize_keyboard=True
    )

def get_main_inline_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="ℹ️ Информация", callback_data="info"),
             InlineKeyboardButton(text="📝 Заявка", callback_data="request")],
            [InlineKeyboardButton(text="🆘 Помощь", callback_data="help"),
             InlineKeyboardButton(text="⚠️ Репорт", callback_data="report")],
            [InlineKeyboardButton(text="📋 Все команды", callback_data="commands")],
            [InlineKeyboardButton(text="📢 Наш канал", url="https://t.me/flowsmp_official"),
             InlineKeyboardButton(text="💬 Дискорд", url="https://discord.gg/Hms7DmfCvt")]
        ]
    )

def get_info_inline_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🏪 Магазин", url="http://shop.flowsmp.online/"),
             InlineKeyboardButton(text="✨ Дискорд", url="https://discord.gg/Hms7DmfCvt")],
            [InlineKeyboardButton(text="✈️ Телеграм", url="https://t.me/flowsmp_official")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main")]
        ]
    )

def get_back_button():
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main")]]
    )

def get_admin_request_keyboard(request_id, user_id, user_name):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Принять", callback_data=f"accept_{request_id}_{user_id}"),
             InlineKeyboardButton(text="❌ Отказать", callback_data=f"reject_{request_id}_{user_id}")]
        ]
    )

def get_admin_report_keyboard(report_id, user_id, user_name):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Принять", callback_data=f"accept_rep_{report_id}_{user_id}"),
             InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_rep_{report_id}_{user_id}")]
        ]
    )

# ==================== FSM СОСТОЯНИЯ ====================
class RequestForm(StatesGroup):
    nickname = State()
    age = State()
    reason = State()

class ReportForm(StatesGroup):
    offender_nick = State()
    reason = State()
    evidence = State()
    time = State()

# ==================== ОБРАБОТЧИКИ ====================
@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_name = message.from_user.first_name
    text = f"""
<b>👋 Приветствую, {user_name}!</b>

В данном боте ты сможешь:
<i>📝 Написать заявку</i>
<i>🔍 Получить информацию</i>
<i>🛠 Получить поддержку</i>

<b>🚀 Выбери действие:</b>
    """
    await message.answer(text, reply_markup=get_main_inline_keyboard())
    await message.answer("📱 Используй кнопки внизу:", reply_markup=get_main_keyboard())

@dp.message(Command("info"))
async def cmd_info(message: Message):
    text = """
ℹ️ <b>Информация о сервере</b>
🌐 IP: <code>mc.flowsmp.online</code>
🏪 <a href='http://shop.flowsmp.online/'>Магазин</a>
✨ <a href='https://discord.gg/Hms7DmfCvt'>Дискорд</a>
✈️ <a href='https://t.me/flowsmp_official'>Телеграм</a>
    """
    await message.answer(text, reply_markup=get_info_inline_keyboard(), disable_web_page_preview=True)

@dp.message(Command("help"))
async def cmd_help(message: Message):
    text = """
🆘 <b>Помощь</b>
/start - Главное меню
/info - Информация
/request - Заявка
/report - Репорт
    """
    await message.answer(text, reply_markup=get_main_keyboard())

@dp.message(Command("request"))
async def cmd_request(message: Message, state: FSMContext):
    await message.answer("📝 Введите ваш ник:", reply_markup=get_cancel_keyboard())
    await state.set_state(RequestForm.nickname)

@dp.message(RequestForm.nickname)
async def process_nickname(message: Message, state: FSMContext):
    if message.text == "❌ ОТМЕНА":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=get_main_keyboard())
        return
    await state.update_data(nickname=message.text)
    await message.answer("⏳ Введите возраст:", reply_markup=get_cancel_keyboard())
    await state.set_state(RequestForm.age)

@dp.message(RequestForm.age)
async def process_age(message: Message, state: FSMContext):
    if message.text == "❌ ОТМЕНА":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=get_main_keyboard())
        return
    await state.update_data(age=message.text)
    await message.answer("⚙️ Почему хотите попасть на сервер:", reply_markup=get_cancel_keyboard())
    await state.set_state(RequestForm.reason)

@dp.message(RequestForm.reason)
async def process_reason(message: Message, state: FSMContext):
    if message.text == "❌ ОТМЕНА":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=get_main_keyboard())
        return
    
    data = await state.get_data()
    request_id = add_request(
        message.from_user.id,
        message.from_user.full_name,
        message.from_user.username,
        data['nickname'],
        data['age'],
        message.text
    )
    
    await message.answer(f"✅ Заявка №{request_id} принята!", reply_markup=get_main_keyboard())
    
    # Уведомление админу
    await bot.send_message(
        ADMIN_ID,
        f"❗️Новая заявка #{request_id}\nОт: {message.from_user.full_name}\nНик: {data['nickname']}",
        reply_markup=get_admin_request_keyboard(request_id, message.from_user.id, message.from_user.full_name)
    )
    await state.clear()

@dp.message(Command("report"))
async def cmd_report(message: Message, state: FSMContext):
    await message.answer("⚠️ Введите ник нарушителя:", reply_markup=get_cancel_keyboard())
    await state.set_state(ReportForm.offender_nick)

@dp.message(ReportForm.offender_nick)
async def process_offender(message: Message, state: FSMContext):
    if message.text == "❌ ОТМЕНА":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=get_main_keyboard())
        return
    await state.update_data(offender_nick=message.text)
    await message.answer("⚙️ Причина репорта:", reply_markup=get_cancel_keyboard())
    await state.set_state(ReportForm.reason)

@dp.message(ReportForm.reason)
async def process_report_reason(message: Message, state: FSMContext):
    if message.text == "❌ ОТМЕНА":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=get_main_keyboard())
        return
    await state.update_data(reason=message.text)
    await message.answer("📎 Доказательства (текст):", reply_markup=get_cancel_keyboard())
    await state.set_state(ReportForm.evidence)

@dp.message(ReportForm.evidence)
async def process_evidence(message: Message, state: FSMContext):
    if message.text == "❌ ОТМЕНА":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=get_main_keyboard())
        return
    await state.update_data(evidence=message.text, evidence_type='text')
    await message.answer("⏳ Время нарушения:", reply_markup=get_cancel_keyboard())
    await state.set_state(ReportForm.time)

@dp.message(ReportForm.time)
async def process_time(message: Message, state: FSMContext):
    if message.text == "❌ ОТМЕНА":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=get_main_keyboard())
        return
    
    data = await state.get_data()
    report_id = add_report(
        message.from_user.id,
        message.from_user.full_name,
        message.from_user.username,
        data['offender_nick'],
        data['reason'],
        data['evidence'],
        data['evidence_type'],
        message.text
    )
    
    await message.answer(f"✅ Репорт №{report_id} отправлен!", reply_markup=get_main_keyboard())
    
    # Уведомление админу
    await bot.send_message(
        ADMIN_ID,
        f"⚠️Новый репорт #{report_id}\nОт: {message.from_user.full_name}\nНа: {data['offender_nick']}\nПричина: {data['reason']}",
        reply_markup=get_admin_report_keyboard(report_id, message.from_user.id, message.from_user.full_name)
    )
    await state.clear()

# ==================== INLINE КНОПКИ ====================
@dp.callback_query()
async def handle_callbacks(callback: CallbackQuery):
    data = callback.data
    
    if data.startswith("accept_"):
        parts = data.split("_")
        request_id = int(parts[1])
        user_id = int(parts[2])
        update_request_status(request_id, 'accepted')
        await bot.send_message(user_id, "✅ Вы приняты! IP: mc.flowsmp.online")
        await callback.message.edit_text(callback.message.text + "\n\n✅ Принято")
        await callback.answer()
    
    elif data.startswith("reject_"):
        parts = data.split("_")
        request_id = int(parts[1])
        user_id = int(parts[2])
        update_request_status(request_id, 'rejected')
        await bot.send_message(user_id, "❌ Вы не приняты. Попробуйте снова /request")
        await callback.message.edit_text(callback.message.text + "\n\n❌ Отклонено")
        await callback.answer()
    
    elif data.startswith("accept_rep_"):
        parts = data.split("_")
        report_id = int(parts[2])
        user_id = int(parts[3])
        update_report_status(report_id, 'accepted')
        await bot.send_message(user_id, "✅ Репорт принят к рассмотрению")
        await callback.message.edit_text(callback.message.text + "\n\n✅ Принято")
        await callback.answer()
    
    elif data.startswith("reject_rep_"):
        parts = data.split("_")
        report_id = int(parts[2])
        user_id = int(parts[3])
        update_report_status(report_id, 'rejected')
        await bot.send_message(user_id, "❌ Репорт отклонён. Недостаточно доказательств")
        await callback.message.edit_text(callback.message.text + "\n\n❌ Отклонено")
        await callback.answer()
    
    elif data == "info":
        await cmd_info(callback.message)
        await callback.answer()
    elif data == "help":
        await cmd_help(callback.message)
        await callback.answer()
    elif data == "back_to_main":
        await cmd_start(callback.message)
        await callback.answer()
    elif data == "commands":
        await callback.message.edit_text(
            "📋 Команды:\n/start\n/info\n/request\n/report\n/help",
            reply_markup=get_back_button()
        )
        await callback.answer()

# ==================== ОБРАБОТКА КНОПОК ====================
@dp.message(F.text)
async def handle_buttons(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state:
        return
    
    text = message.text
    if text == "⚡️Старт":
        await cmd_start(message)
    elif text == "ℹ️ Информация":
        await cmd_info(message)
    elif text == "📝 Заявка":
        await cmd_request(message, state)
    elif text == "🆘 Помощь":
        await cmd_help(message)
    elif text == "⚠️ Репорт":
        await cmd_report(message, state)

# ==================== ЗАПУСК ====================
def run_bot():
    asyncio.run(dp.start_polling(bot))

@app.route('/')
def index():
    return jsonify({"status": "Бот работает", "mode": "polling"})

@app.route('/health')
def health():
    return jsonify({"status": "healthy"}), 200

if __name__ == "__main__":
    # Запускаем бота в фоне
    thread = threading.Thread(target=run_bot, daemon=True)
    thread.start()
    logger.info("✅ Бот запущен")
    
    # Запускаем Flask
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
