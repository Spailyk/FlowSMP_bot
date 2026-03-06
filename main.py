import os
import logging
import sqlite3
import asyncio
from datetime import datetime
from contextlib import asynccontextmanager

from flask import Flask, request, jsonify
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import threading
import time

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
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Flask приложение для health check
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# ==================== ФУНКЦИИ РАБОТЫ С БД ====================
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
    cur.execute('UPDATE requests SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?', (status, request_id))
    conn.commit()
    conn.close()

def update_request_field(request_id, field, value):
    conn = sqlite3.connect('bot.db')
    cur = conn.cursor()
    cur.execute(f'UPDATE requests SET {field} = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?', (value, request_id))
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
    cur.execute('UPDATE reports SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?', (status, report_id))
    conn.commit()
    conn.close()

def get_stats():
    conn = sqlite3.connect('bot.db')
    cur = conn.cursor()
    cur.execute("SELECT status, COUNT(*) FROM requests GROUP BY status")
    req_stats = dict(cur.fetchall())
    cur.execute("SELECT status, COUNT(*) FROM reports GROUP BY status")
    rep_stats = dict(cur.fetchall())
    conn.close()
    return req_stats, rep_stats

# ==================== КЛАВИАТУРЫ ====================
def get_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⚡️Старт")],
            [KeyboardButton(text="ℹ️ Информация"), KeyboardButton(text="📝 Заявка")],
            [KeyboardButton(text="🆘 Помощь"), KeyboardButton(text="⚠️ Репорт")]
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие..."
    )

def get_cancel_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ ОТМЕНА")]],
        resize_keyboard=True,
        input_field_placeholder="Нажмите ❌ ОТМЕНА для выхода..."
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
            [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="back_to_main")]
        ]
    )

def get_back_button():
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад в меню", callback_data="back_to_main")]]
    )

def get_admin_request_keyboard(request_id, user_id, user_name):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Принять", callback_data=f"accept_request_{request_id}_{user_id}_{user_name}"),
             InlineKeyboardButton(text="❌ Отказать", callback_data=f"reject_request_{request_id}_{user_id}_{user_name}")]
        ]
    )

def get_admin_report_keyboard(report_id, user_id, user_name):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Принять", callback_data=f"accept_report_{report_id}_{user_id}_{user_name}"),
             InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_report_{report_id}_{user_id}_{user_name}")]
        ]
    )

def get_edit_keyboard(request_id):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Ник", callback_data=f"edit_req_{request_id}_nickname"),
             InlineKeyboardButton(text="✏️ Возраст", callback_data=f"edit_req_{request_id}_age")],
            [InlineKeyboardButton(text="✏️ Причина", callback_data=f"edit_req_{request_id}_reason")],
            [InlineKeyboardButton(text="❌ Закрыть", callback_data="close_edit")]
        ]
    )

# ==================== FSM СОСТОЯНИЯ ====================
class RequestForm(StatesGroup):
    nickname = State()
    age = State()
    reason = State()
    edit_field = State()
    edit_value = State()

class ReportForm(StatesGroup):
    offender_nick = State()
    reason = State()
    evidence = State()
    time = State()

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
async def send_error_message(message: Message):
    text = """
❌ <b>Данной команды не существует</b>

⛏️ <b>Используйте:</b>
• /start            ⭐️
• /request      📄
• /help             ❓
• /report         ⚠️
• /info              ℹ️
    """
    await message.answer(text, parse_mode="HTML", reply_markup=get_main_keyboard())

async def send_welcome(message: Message):
    user_name = message.from_user.first_name
    text = f"""
<b>👋 Приветствую, {user_name}!</b>

В данном боте ты сможешь:

<i>📝 Написать заявку</i>
<i>🔍 Получить информацию</i>
<i>🛠 Получить поддержку</i>
<i>🛒 И многое другое...</i>

<b>🚀 Начнём? Пожалуй.</b>

✨ <u>Выбери действие</u> с помощью кнопок ниже:
    """
    await message.answer(text, parse_mode="HTML", reply_markup=get_main_inline_keyboard())
    await message.answer("📱 Также ты можешь использовать кнопки внизу экрана:", reply_markup=get_main_keyboard())

async def cancel_request_action(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ <b>Заявка отменена</b>\n👇 <b>Написать заявку:</b>\n/request", parse_mode="HTML", reply_markup=get_main_keyboard())

async def cancel_report_action(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ <b>Репорт отменен</b>\n👇 <b>Написать репорт:</b>\n/report", parse_mode="HTML", reply_markup=get_main_keyboard())

# ==================== ОБРАБОТЧИКИ КОМАНД ====================
@dp.message(Command("start"))
async def cmd_start(message: Message):
    await send_welcome(message)

@dp.message(Command("info"))
async def cmd_info(message: Message):
    text = """
ℹ️ <b>Информация о сервере</b>

🌐 <b>IP-адрес:</b> <code>mc.flowsmp.online</code>
🏪 <b>Магазин:</b> <a href='http://shop.flowsmp.online/'>ТЫК</a>
✨ <b>Дискорд:</b> <a href='https://discord.gg/Hms7DmfCvt'>ТЫК</a>
✈️ <b>Телеграм:</b> <a href='https://t.me/flowsmp_official'>ТЫК</a>
    """
    await message.answer(text, parse_mode="HTML", reply_markup=get_info_inline_keyboard(), disable_web_page_preview=True)

@dp.message(Command("help"))
async def cmd_help(message: Message):
    text = """
🆘 <b>Помощь</b>

<b>Доступные команды:</b>
• /start - Главное меню 
• /info - Информация 
• /request - Создать заявку
• /help - Помощь
• /report - Репорт на игрока 
• /profile - Статистика (только админ)

<b>Часто задаваемые вопросы:</b>

❓ Как создать заявку?
→ Используй команду /request и следуй инструкциям

❓ Как пожаловаться на игрока?
→ Используй команду /report (можно прикрепить фото/видео)
    """
    await message.answer(text, parse_mode="HTML", reply_markup=get_main_keyboard())

@dp.message(Command("profile"))
async def cmd_profile(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ У вас нет прав для этой команды.")
        return
    req_stats, rep_stats = get_stats()
    text = f"""
<b>📊 Статистика бота</b>

<b>Заявки:</b>
• Всего: {sum(req_stats.values())}
• В ожидании: {req_stats.get('pending', 0)}
• Принято: {req_stats.get('accepted', 0)}
• Отклонено: {req_stats.get('rejected', 0)}

<b>Репорты:</b>
• Всего: {sum(rep_stats.values())}
• В ожидании: {rep_stats.get('pending', 0)}
• Принято: {rep_stats.get('accepted', 0)}
• Отклонено: {rep_stats.get('rejected', 0)}
    """
    await message.answer(text, parse_mode="HTML", reply_markup=get_main_keyboard())

@dp.message(Command("request"))
async def cmd_request(message: Message, state: FSMContext):
    text = """
📝 <b>Написать заявку</b>

📩 <b>Пункты для подачи заявки:</b>
1. Ваш ник 👤
2. Возраст ⏳
3. Почему вы хотите попасть на сервер ⚙️

<i>Пожалуйста, введите ваш ник:</i>
    """
    await message.answer(text, parse_mode="HTML", reply_markup=get_cancel_keyboard())
    await state.set_state(RequestForm.nickname)

@dp.message(RequestForm.nickname)
async def process_nickname(message: Message, state: FSMContext):
    if message.text == "❌ ОТМЕНА":
        await cancel_request_action(message, state)
        return
    await state.update_data(nickname=message.text)
    await message.answer("⏳ <b>Введите ваш возраст:</b>", parse_mode="HTML", reply_markup=get_cancel_keyboard())
    await state.set_state(RequestForm.age)

@dp.message(RequestForm.age)
async def process_age(message: Message, state: FSMContext):
    if message.text == "❌ ОТМЕНА":
        await cancel_request_action(message, state)
        return
    await state.update_data(age=message.text)
    await message.answer("⚙️ <b>Почему вы хотите попасть на сервер:</b>", parse_mode="HTML", reply_markup=get_cancel_keyboard())
    await state.set_state(RequestForm.reason)

@dp.message(RequestForm.reason)
async def process_reason(message: Message, state: FSMContext):
    if message.text == "❌ ОТМЕНА":
        await cancel_request_action(message, state)
        return
    data = await state.get_data()
    user_id = message.from_user.id
    user_name = message.from_user.full_name
    username = message.from_user.username

    request_id = add_request(user_id, user_name, username, data['nickname'], data['age'], message.text)

    success_text = f"""
✅ <b>Заявка успешно подана!</b> (ID: {request_id})
🕘 <i>Она будет рассмотрена в кратчайшие сроки</i>

Спасибо за обращение! Мы свяжемся с вами.
    """
    await message.answer(success_text, parse_mode="HTML", reply_markup=get_main_keyboard())

    edit_kb = get_edit_keyboard(request_id)
    await message.answer("✏️ Если хотите отредактировать заявку, нажмите кнопку ниже:", reply_markup=edit_kb)

    user_info = f"@{username}" if username else f"<a href='tg://user?id={user_id}'>{user_name}</a>"
    admin_text = f"""
<b>❗️ Новая заявка</b> (ID: {request_id})

<b>Отправитель:</b> {user_info}
<b>ID:</b> <code>{user_id}</code>

1) Ник: <code>{data['nickname']}</code>
2) Возраст: <code>{data['age']}</code>
3) Причина: <code>{message.text}</code>

<b>✨ Выберите действие:</b>
    """
    await bot.send_message(ADMIN_ID, admin_text, parse_mode="HTML",
                           reply_markup=get_admin_request_keyboard(request_id, user_id, user_name),
                           disable_web_page_preview=True)
    await state.clear()

# ==================== РЕДАКТИРОВАНИЕ ЗАЯВКИ ====================
@dp.callback_query(lambda c: c.data.startswith('edit_req_'))
async def edit_request_callback(callback: CallbackQuery, state: FSMContext):
    _, _, request_id, field = callback.data.split('_')
    request_id = int(request_id)
    await state.update_data(edit_request_id=request_id, edit_field=field)
    if field == 'nickname':
        await callback.message.edit_text("✏️ Введите новый ник:")
    elif field == 'age':
        await callback.message.edit_text("✏️ Введите новый возраст:")
    elif field == 'reason':
        await callback.message.edit_text("✏️ Введите новую причину:")
    await state.set_state(RequestForm.edit_value)
    await callback.answer()

@dp.message(RequestForm.edit_value)
async def process_edit_value(message: Message, state: FSMContext):
    data = await state.get_data()
    request_id = data['edit_request_id']
    field = data['edit_field']
    new_value = message.text

    update_request_field(request_id, field, new_value)

    await message.answer("✅ Заявка успешно обновлена!", reply_markup=get_main_keyboard())
    await state.clear()

@dp.callback_query(lambda c: c.data == 'close_edit')
async def close_edit_callback(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer()

# ==================== РЕПОРТЫ С МЕДИА ====================
@dp.message(Command("report"))
async def cmd_report(message: Message, state: FSMContext):
    text = """
⚠️ <b>Репорт на игрока</b>

📩 <b>Пункты для подачи репорта:</b>
1. Ник нарушителя 👤
2. Причина репорта ⚙️
3. Доказательства 📎 (можно отправить фото, видео или текст)
4. Дата и время нарушения ⏳

<i>Пожалуйста, введите ник нарушителя:</i>
    """
    await message.answer(text, parse_mode="HTML", reply_markup=get_cancel_keyboard())
    await state.set_state(ReportForm.offender_nick)

@dp.message(ReportForm.offender_nick)
async def process_offender_nick(message: Message, state: FSMContext):
    if message.text == "❌ ОТМЕНА":
        await cancel_report_action(message, state)
        return
    await state.update_data(offender_nick=message.text)
    await message.answer("⚙️ <b>Укажите причину репорта:</b>", parse_mode="HTML", reply_markup=get_cancel_keyboard())
    await state.set_state(ReportForm.reason)

@dp.message(ReportForm.reason)
async def process_report_reason(message: Message, state: FSMContext):
    if message.text == "❌ ОТМЕНА":
        await cancel_report_action(message, state)
        return
    await state.update_data(reason=message.text)
    await message.answer(
        "📎 <b>Предоставьте доказательства:</b>\n\n"
        "<i>(отправьте фото, видео или напишите текст)</i>",
        parse_mode="HTML",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(ReportForm.evidence)

@dp.message(ReportForm.evidence)
async def process_evidence(message: Message, state: FSMContext):
    if message.text == "❌ ОТМЕНА":
        await cancel_report_action(message, state)
        return

    evidence_text = None
    file_path = None
    evidence_type = 'text'

    if message.photo:
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        filename = f"report_photo_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{message.from_user.id}.jpg"
        file_path = os.path.join(REPORTS_MEDIA_DIR, filename)
        await bot.download_file(file.file_path, file_path)
        evidence_type = 'photo'
        evidence_text = file_path
    elif message.video:
        video = message.video
        file = await bot.get_file(video.file_id)
        ext = os.path.splitext(video.file_name)[1] if video.file_name else '.mp4'
        filename = f"report_video_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{message.from_user.id}{ext}"
        file_path = os.path.join(REPORTS_MEDIA_DIR, filename)
        await bot.download_file(file.file_path, file_path)
        evidence_type = 'video'
        evidence_text = file_path
    elif message.text:
        evidence_text = message.text
        evidence_type = 'text'
    else:
        await message.answer("❌ Пожалуйста, отправьте текст, фото или видео.")
        return

    await state.update_data(evidence=evidence_text, evidence_type=evidence_type)
    await message.answer(
        "⏳ <b>Укажите дату и время нарушения:</b>\n\n"
        "<i>(например: 05.03.2025, 15:30)</i>",
        parse_mode="HTML",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(ReportForm.time)

@dp.message(ReportForm.time)
async def process_time(message: Message, state: FSMContext):
    if message.text == "❌ ОТМЕНА":
        await cancel_report_action(message, state)
        return

    data = await state.get_data()
    user_id = message.from_user.id
    user_name = message.from_user.full_name
    username = message.from_user.username

    report_id = add_report(
        user_id, user_name, username,
        data['offender_nick'], data['reason'],
        data['evidence'], data['evidence_type'], message.text
    )

    success_text = f"""
✅ <b>Репорт успешно отправлен!</b> (ID: {report_id})
🕘 <i>Он будет рассмотрен в кратчайшие сроки</i>

Спасибо за помощь в поддержании порядка на сервере!
    """
    await message.answer(success_text, parse_mode="HTML", reply_markup=get_main_keyboard())

    user_info = f"@{username}" if username else f"<a href='tg://user?id={user_id}'>{user_name}</a>"
    admin_text = f"""
<b>⚠️ Новый репорт</b> (ID: {report_id})

<b>Отправитель:</b> {user_info}
<b>ID:</b> <code>{user_id}</code>

1) Ник нарушителя: <code>{data['offender_nick']}</code>
2) Причина: <code>{data['reason']}</code>
3) Доказательства: 
    """
    if data['evidence_type'] == 'photo':
        await bot.send_photo(ADMIN_ID, FSInputFile(data['evidence']), caption=admin_text, parse_mode="HTML",
                             reply_markup=get_admin_report_keyboard(report_id, user_id, user_name))
    elif data['evidence_type'] == 'video':
        await bot.send_video(ADMIN_ID, FSInputFile(data['evidence']), caption=admin_text, parse_mode="HTML",
                             reply_markup=get_admin_report_keyboard(report_id, user_id, user_name))
    else:
        admin_text += f"<code>{data['evidence']}</code>\n4) Время: <code>{message.text}</code>"
        await bot.send_message(ADMIN_ID, admin_text, parse_mode="HTML",
                               reply_markup=get_admin_report_keyboard(report_id, user_id, user_name),
                               disable_web_page_preview=True)

    await state.clear()

# ==================== НЕИЗВЕСТНЫЕ КОМАНДЫ ====================
@dp.message(F.text.startswith("/"))
async def handle_unknown_command(message: Message):
    known = ["/start", "/request", "/help", "/report", "/info", "/profile"]
    cmd = message.text.split()[0].lower()
    if cmd not in known:
        await send_error_message(message)

# ==================== INLINE КНОПКИ ====================
@dp.callback_query()
async def handle_callbacks(callback: CallbackQuery, state: FSMContext):
    action = callback.data

    if action.startswith("accept_request_"):
        parts = action.split("_")
        request_id = int(parts[2])
        user_id = int(parts[3])
        user_name = parts[4]
        update_request_status(request_id, 'accepted')
        accept_text = f"""
<b>🔥 Поздравляю, {user_name}!</b>

✅ <b>Ты - принят</b>
IP-адрес сервера: <code>mc.flowsmp.online</code>
        """
        await bot.send_message(user_id, accept_text, parse_mode="HTML")
        await callback.message.edit_text(callback.message.text + "\n\n✅ Заявка <b>принята</b>!", parse_mode="HTML")
        await callback.answer("✅ Заявка принята")

    elif action.startswith("reject_request_"):
        parts = action.split("_")
        request_id = int(parts[2])
        user_id = int(parts[3])
        user_name = parts[4]
        update_request_status(request_id, 'rejected')
        reject_text = f"""
<b>⚒️ Сожалею, {user_name}!</b>

❌ <b>Ты - не принят.</b>
📌 <b>Подать заявку ещё раз - ты сможешь прямо сейчас!</b>

Используй команду /request
        """
        await bot.send_message(user_id, reject_text, parse_mode="HTML", reply_markup=get_main_keyboard())
        await callback.message.edit_text(callback.message.text + "\n\n❌ Заявка <b>отклонена</b>!", parse_mode="HTML")
        await callback.answer("❌ Заявка отклонена")

    elif action.startswith("accept_report_"):
        parts = action.split("_")
        report_id = int(parts[2])
        user_id = int(parts[3])
        user_name = parts[4]
        update_report_status(report_id, 'accepted')
        accept_text = f"""
<b>✅ Уважаемый, {user_name}!</b>

<b>Ваш репорт принят и будет рассмотрен администрацией.</b>

Спасибо за помощь в поддержании порядка!
        """
        await bot.send_message(user_id, accept_text, parse_mode="HTML")
        await callback.message.edit_text(callback.message.text + "\n\n✅ Репорт <b>принят к рассмотрению</b>!", parse_mode="HTML")
        await callback.answer("✅ Репорт принят")

    elif action.startswith("reject_report_"):
        parts = action.split("_")
        report_id = int(parts[2])
        user_id = int(parts[3])
        user_name = parts[4]
        update_report_status(report_id, 'rejected')
        reject_text = f"""
<b>❌ Уважаемый, {user_name}!</b>

<b>Ваш репорт отклонен</b> по следующим причинам:
• Недостаточно доказательств
• Нарушение правил подачи репорта

📌 <b>Подать репорт ещё раз - ты сможешь прямо сейчас!</b>
Используй команду /report
        """
        await bot.send_message(user_id, reject_text, parse_mode="HTML", reply_markup=get_main_keyboard())
        await callback.message.edit_text(callback.message.text + "\n\n❌ Репорт <b>отклонен</b>!", parse_mode="HTML")
        await callback.answer("❌ Репорт отклонен")

    elif action == "info":
        text = """
ℹ️ <b>Информация о сервере</b>

🌐 <b>IP-адрес:</b> <code>mc.flowsmp.online</code>
🏪 <b>Магазин:</b> <a href='http://shop.flowsmp.online/'>ТЫК</a>
✨ <b>Дискорд:</b> <a href='https://discord.gg/Hms7DmfCvt'>ТЫК</a>
✈️ <b>Телеграм:</b> <a href='https://t.me/flowsmp_official'>ТЫК</a>
        """
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_info_inline_keyboard(), disable_web_page_preview=True)

    elif action == "request":
        text = """
📝 <b>Создание заявки</b>

Для создания заявки используй команду:
<code>/request</code>

<b>Пункты для подачи заявки:</b>
1. Ваш ник 👤
2. Возраст ⏳
3. Почему вы хотите попасть на сервер ⚙️

<i>Нажми /request и следуй инструкциям</i>
        """
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_back_button())

    elif action == "help":
        text = """
🆘 <b>Помощь</b>

<b>Доступные команды:</b>
• /start - Главное меню 
• /info - Информация 
• /request - Создать заявку
• /help - Помощь
• /report - Репорт на игрока 
• /profile - Статистика (только админ)

<b>Часто задаваемые вопросы:</b>

❓ Как создать заявку?
→ Используй команду /request и следуй инструкциям

❓ Как пожаловаться на игрока?
→ Используй команду /report (можно прикрепить фото/видео)
        """
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_back_button())

    elif action == "report":
        text = """
⚠️ <b>Репорт на игрока</b>

Для подачи репорта используй команду:
<code>/report</code>

<b>Пункты для подачи репорта:</b>
1. Ник нарушителя 👤
2. Причина репорта ⚙️
3. Доказательства 📎 (фото, видео или текст)
4. Дата и время нарушения ⏳

<i>Нажми /report и следуй инструкциям</i>
        """
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_back_button())

    elif action == "commands":
        text = """
📋 <b>Список всех команд:</b>

<b>Основные команды:</b>
/start - Начать работу ⭐️
/info - Информация ℹ️
/request - Создать заявку 📄
/help - Помощь ❓
/report - Репорт на игрока ⚠️
/profile - Статистика (админ) 📊
        """
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_back_button())

    elif action == "back_to_main":
        user_name = callback.from_user.first_name
        text = f"""
<b>👋 С возвращением, {user_name}!</b>

✨ <u>Выбери действие</u> с помощью кнопок ниже:
        """
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_main_inline_keyboard())

    await callback.answer()

# ==================== ОБРАБОТКА КНОПОК КЛАВИАТУРЫ ====================
@dp.message(F.text)
async def handle_buttons(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state:
        if message.text == "❌ ОТМЕНА":
            if "RequestForm" in current_state:
                await cancel_request_action(message, state)
            elif "ReportForm" in current_state:
                await cancel_report_action(message, state)
        return

    text = message.text
    if text == "⚡️Старт":
        await send_welcome(message)
    elif text == "ℹ️ Информация":
        await cmd_info(message)
    elif text == "📝 Заявка":
        await cmd_request(message, state)
    elif text == "🆘 Помощь":
        await cmd_help(message)
    elif text == "⚠️ Репорт":
        await cmd_report(message, state)

# ==================== ЗАПУСК БОТА В ОТДЕЛЬНОМ ПОТОКЕ ====================
def run_bot():
    """Запускает polling бота в отдельном потоке"""
    asyncio.run(dp.start_polling(bot))

@app.route('/')
def index():
    return jsonify({"status": "Bot is running", "mode": "polling"})

@app.route('/health')
def health():
    return jsonify({"status": "healthy"}), 200

# ==================== ОСНОВНОЙ ЗАПУСК ====================
if __name__ == "__main__":
    # Запускаем бота в отдельном потоке
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    logger.info("✅ Bot polling thread started")
    
    # Запускаем Flask сервер
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
