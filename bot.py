import logging
from aiogram import Bot, Dispatcher, executor, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ParseMode
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.dispatcher.filters import CommandStart
from datetime import datetime
import os
from environs import Env
import gspread
from google.oauth2.service_account import Credentials
import platform
import sqlite3
import psycopg2
from psycopg2 import sql, IntegrityError
import re

# Загрузка переменных окружения
env = Env()
env.read_env()
API_TOKEN = env.str('BOT_TOKEN')

logging.basicConfig(level=logging.INFO)

bot = Bot(token=API_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher(bot, storage=MemoryStorage())

# Состояния
class Form(StatesGroup):
    type = State()  # Kirim/Ciqim
    nomi = State()  # Сразу после типа
    category = State()
    loyiha = State()  # Новый шаг
    amount = State()
    pay_type = State()
    comment = State()

# Кнопки выбора Kirim/Chiqim
start_kb = InlineKeyboardMarkup(row_width=2)
start_kb.add(
    InlineKeyboardButton('🟢 Kirim', callback_data='type_kirim'),
    InlineKeyboardButton('🔴 Chiqim', callback_data='type_chiqim')
)

# Категории
categories = [
    ("🟥 Doimiy Xarajat", "cat_doimiy"),
    ("🟩 Oʻzgaruvchan Xarajat", "cat_ozgaruvchan"),
    ("🟪 Qarz", "cat_qarz"),
    ("⚪ Avtoprom", "cat_avtoprom"),
    ("🟩 Divident", "cat_divident"),
    ("🟪 Soliq", "cat_soliq"),
    ("🟦 Ish Xaqi", "cat_ishhaqi")
]

# Словарь соответствий: категория -> эмодзи
category_emojis = {
    "Qurilish materiallari": "🟩",
    "Doimiy Xarajat": "🟥",
    "Qarz": "🟪",
    "Divident": "🟩",
    "Soliq": "🟪",
    "Ish Xaqi": "🟦",
    # Добавьте другие категории и эмодзи по мере необходимости
}

def get_category_with_emoji(category_name):
    emoji = category_emojis.get(category_name, "")
    return f"{emoji} {category_name}".strip()

def get_categories_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    for name in get_categories():
        cb = f"cat_{name}"
        # Показываем эмодзи в меню
        btn_text = get_category_with_emoji(name)
        kb.add(InlineKeyboardButton(btn_text, callback_data=cb))
    return kb

# Тип оплаты
pay_types = [
    ("Plastik", "pay_plastik"),
    ("Naxt", "pay_naxt"),
    ("Perevod", "pay_perevod"),
    ("Bank", "pay_bank")
]

def get_pay_types_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    for name in get_pay_types():
        cb = f"pay_{name}"
        kb.add(InlineKeyboardButton(name, callback_data=cb))
    return kb

# Кнопка пропуска для Izoh
skip_kb = InlineKeyboardMarkup().add(InlineKeyboardButton("Пропустить", callback_data="skip_comment"))

# Кнопки подтверждения
confirm_kb = InlineKeyboardMarkup(row_width=2)
confirm_kb.add(
    InlineKeyboardButton('✅ Ha', callback_data='confirm_yes'),
    InlineKeyboardButton('❌ Yoq', callback_data='confirm_no')
)

# --- Google Sheets settings ---
SHEET_ID = '1UN8RvU-i3JlQG7HxlbzopXTzlbYoB6NC_U_Nwfytttk'
SHEET_NAME = 'Kirim/chiqim'
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
CREDENTIALS_FILE = 'credentials.json'

def clean_emoji(text):
    # Удаляет только эмодзи/спецсимволы в начале строки, остальной текст не трогает
    return re.sub(r'^[^\w\s]+', '', text).strip()

def add_to_google_sheet(data):
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SHEET_ID)
    worksheet = sh.worksheet(SHEET_NAME)
    # Jadval ustunlari: Kun, Summa, Nomi, Kirim-Chiqim, To'lov turi, Kategoriyalar, Izoh, Vaqt
    from datetime import datetime
    now = datetime.now()
    if platform.system() == 'Windows':
        date_str = now.strftime('%m/%d/%Y')
    else:
        date_str = now.strftime('%-m/%-d/%Y')
    time_str = now.strftime('%H:%M')
    user_name = get_user_name(data.get('user_id', data.get('user_id', '')))
    row = [
        date_str,      # Kun
        time_str,      # Vaqt
        data.get('amount', ''),           # Summa
        data.get('nomi', ''),             # Nomi
        clean_emoji(data.get('type', '')), # Kirim-Chiqim
        data.get('pay_type', ''),         # To'lov turi
        clean_emoji(data.get('category', '')), # Kategoriyalar
        data.get('loyiha', ''),           # Loyihalar
        data.get('comment', ''),          # Izoh
        '',                               # Oylik ko'rsatkich (если не используется)
        user_name                         # User (последний столбец)
    ]
    worksheet.append_row(row)

def format_summary(data):
    tur_emoji = '🟢' if data.get('type') == 'Kirim' else '🔴'
    dt = data.get('dt', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    # Показываем категорию с эмодзи
    category_with_emoji = get_category_with_emoji(data.get('category', '-'))
    return (
        f"<b>Natija:</b>\n"
        f"<b>Tur:</b> {tur_emoji} {data.get('type', '-')}\n"
        f"<b>Nomi:</b> {data.get('nomi', '-')}\n"
        f"<b>Kotegoriya:</b> {category_with_emoji}\n"
        f"<b>Loyiha:</b> {data.get('loyiha', '-')}\n"
        f"<b>Summa:</b> {data.get('amount', '-')}\n"
        f"<b>To'lov turi:</b> {data.get('pay_type', '-')}\n"
        f"<b>Izoh:</b> {data.get('comment', '-')}\n"
        f"<b>Vaqt:</b> {dt}"
    )

# --- Админы ---
ADMINS = [5657091547, 5048593195]  # Здесь можно добавить id других админов через запятую

# --- Инициализация БД ---
def get_db_conn():
    return psycopg2.connect(
        dbname=env.str('POSTGRES_DB', 'kapital'),
        user=env.str('POSTGRES_USER', 'postgres'),
        password=env.str('POSTGRES_PASSWORD', 'postgres'),
        host=env.str('POSTGRES_HOST', 'localhost'),
        port=env.str('POSTGRES_PORT', '5432')
    )

def init_db():
    conn = get_db_conn()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        user_id BIGINT UNIQUE,
        name TEXT,
        phone TEXT,
        status TEXT,
        reg_date TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS pay_types (
        id SERIAL PRIMARY KEY,
        name TEXT UNIQUE
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS categories (
        id SERIAL PRIMARY KEY,
        name TEXT UNIQUE
    )''')
    # Заполняем дефолтные значения, если таблицы пусты
    c.execute('SELECT COUNT(*) FROM pay_types')
    if c.fetchone()[0] == 0:
        for name in ["Plastik", "Naxt", "Perevod", "Bank"]:
            c.execute('INSERT INTO pay_types (name) VALUES (%s)', (name,))
    c.execute('SELECT COUNT(*) FROM categories')
    if c.fetchone()[0] == 0:
        for name in ["🟥 Doimiy Xarajat", "🟩 Oʻzgaruvchan Xarajat", "🟪 Qarz", "⚪ Avtoprom", "🟩 Divident", "🟪 Soliq", "🟦 Ish Xaqi"]:
            c.execute('INSERT INTO categories (name) VALUES (%s)', (name,))
    conn.commit()
    conn.close()

init_db()

# --- Проверка статуса пользователя ---
def get_user_status(user_id):
    conn = get_db_conn()
    c = conn.cursor()
    c.execute('SELECT status FROM users WHERE user_id=%s', (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

# --- Регистрация пользователя ---
def register_user(user_id, name, phone):
    from datetime import datetime
    conn = get_db_conn()
    c = conn.cursor()
    try:
        c.execute('INSERT INTO users (user_id, name, phone, status, reg_date) VALUES (%s, %s, %s, %s, %s) ON CONFLICT (user_id) DO NOTHING',
                  (user_id, name, phone, 'pending', datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        conn.commit()
    except IntegrityError:
        conn.rollback()
    conn.close()

# --- Обновление статуса пользователя ---
def update_user_status(user_id, status):
    conn = get_db_conn()
    c = conn.cursor()
    c.execute('UPDATE users SET status=%s WHERE user_id=%s', (status, user_id))
    conn.commit()
    conn.close()

# --- Получение имени пользователя для Google Sheets ---
def get_user_name(user_id):
    conn = get_db_conn()
    c = conn.cursor()
    c.execute('SELECT name FROM users WHERE user_id=%s', (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else ''

# --- Получение актуальных списков ---
def get_pay_types():
    conn = get_db_conn()
    c = conn.cursor()
    c.execute('SELECT name FROM pay_types')
    result = [row[0] for row in c.fetchall()]
    conn.close()
    return result

def get_categories():
    conn = get_db_conn()
    c = conn.cursor()
    c.execute('SELECT name FROM categories')
    result = [row[0] for row in c.fetchall()]
    conn.close()
    return result

# --- Старт с регистрацией ---
@dp.message_handler(commands=['start'])
async def start(msg: types.Message, state: FSMContext):
    user_id = msg.from_user.id
    status = get_user_status(user_id)
    if status == 'approved':
        await state.finish()
        text = "<b>Qaysi turdagi operatsiya?</b>"
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            InlineKeyboardButton('🟢 Kirim', callback_data='type_kirim'),
            InlineKeyboardButton('🔴 Chiqim', callback_data='type_chiqim')
        )
        await msg.answer(text, reply_markup=kb)
        await Form.type.set()
    elif status == 'pending':
        await msg.answer('⏳ Sizning arizangiz ko‘rib chiqilmoqda. Iltimos, kuting.')
    elif status == 'denied':
        await msg.answer('❌ Sizga botdan foydalanishga ruxsat berilmagan.')
    else:
        await msg.answer('Ismingizni kiriting:')
        await state.set_state('register_name')

# --- FSM для регистрации ---
from aiogram.dispatcher.filters.state import State, StatesGroup
class Register(StatesGroup):
    name = State()
    phone = State()

@dp.message_handler(state='register_name', content_types=types.ContentTypes.TEXT)
async def process_register_name(msg: types.Message, state: FSMContext):
    await state.update_data(name=msg.text.strip())
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.add(types.KeyboardButton("📱 Telefon raqamni yuborish", request_contact=True))
    await msg.answer('Telefon raqamingizni yuboring:', reply_markup=kb)
    await state.set_state('register_phone')

@dp.message_handler(state='register_phone', content_types=types.ContentTypes.CONTACT)
async def process_register_phone(msg: types.Message, state: FSMContext):
    phone = msg.contact.phone_number
    data = await state.get_data()
    user_id = msg.from_user.id
    name = data.get('name', '')
    register_user(user_id, name, phone)
    await msg.answer('⏳ Arizangiz adminga yuborildi. Iltimos, kuting.', reply_markup=types.ReplyKeyboardRemove())
    # Уведомление админа
    for admin_id in ADMINS:
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            InlineKeyboardButton('✅ Ha', callback_data=f'approve_{user_id}'),
            InlineKeyboardButton('❌ Yoq', callback_data=f'deny_{user_id}')
        )
        await bot.send_message(admin_id, f'🆕 Yangi foydalanuvchi ro‘yxatdan o‘tdi:\nID: <code>{user_id}</code>\nIsmi: <b>{name}</b>\nTelefon: <code>{phone}</code>', reply_markup=kb)
    await state.finish()

# --- Обработка одобрения/запрета админом ---
@dp.callback_query_handler(lambda c: c.data.startswith('approve_') or c.data.startswith('deny_'), state='*')
async def process_admin_approve(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMINS:
        await call.answer('Faqat admin uchun!', show_alert=True)
        return
    action, user_id = call.data.split('_')
    user_id = int(user_id)
    if action == 'approve':
        update_user_status(user_id, 'approved')
        await bot.send_message(user_id, '✅ Sizga botdan foydalanishga ruxsat berildi! /start')
        await call.message.edit_text('✅ Foydalanuvchi tasdiqlandi.')
    else:
        update_user_status(user_id, 'denied')
        await bot.send_message(user_id, '❌ Sizga botdan foydalanishga ruxsat berilmagan.')
        await call.message.edit_text('❌ Foydalanuvchi rad etildi.')
    await call.answer()

# --- Ограничение доступа для всех остальных хендлеров ---
@dp.message_handler(lambda msg: get_user_status(msg.from_user.id) != 'approved', state='*')
async def block_unapproved(msg: types.Message, state: FSMContext):
    await msg.answer('⏳ Sizning arizangiz ko‘rib chiqilmoqda yoki sizga ruxsat berilmagan.')
    await state.finish()

# Старт
@dp.message_handler(CommandStart())
async def start(msg: types.Message, state: FSMContext):
    await state.finish()
    text = "<b>Qaysi turdagi operatsiya?</b>"
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton('🟢 Kirim', callback_data='type_kirim'),
        InlineKeyboardButton('🔴 Chiqim', callback_data='type_chiqim')
    )
    await msg.answer(text, reply_markup=kb)
    await Form.type.set()

# Kirim/Ciqim выбор
@dp.callback_query_handler(lambda c: c.data.startswith('type_'), state=Form.type)
async def process_type(call: types.CallbackQuery, state: FSMContext):
    t = 'Kirim' if call.data == 'type_kirim' else 'Ciqim'
    await state.update_data(type=t)
    await call.message.edit_text("<b>Xarajat yoki daromad nomini yozing</b>")
    await Form.nomi.set()
    await call.answer()

# Nomi (обязательное поле)
@dp.message_handler(state=Form.nomi, content_types=types.ContentTypes.TEXT)
async def process_nomi(msg: types.Message, state: FSMContext):
    await state.update_data(nomi=msg.text)
    await msg.answer("<b>Kotegoriyani tanlang:</b>", reply_markup=get_categories_kb())
    await Form.category.set()

# Категория
@dp.callback_query_handler(lambda c: c.data.startswith('cat_'), state=Form.category)
async def process_category(call: types.CallbackQuery, state: FSMContext):
    cat = call.data[4:]
    await state.update_data(category=cat)
    # Шаг выбора Loyihalar
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton('UzAvtosanoat', callback_data='loyiha_UzAvtosanoat'),
        InlineKeyboardButton('Bodomzor', callback_data='loyiha_Bodomzor'),
        InlineKeyboardButton('Boshqa', callback_data='loyiha_Boshqa')
    )
    await call.message.edit_text("<b>Loyihani tanlang:</b>", reply_markup=kb)
    await Form.loyiha.set()
    await call.answer()

# Обработка выбора Loyihalar
@dp.callback_query_handler(lambda c: c.data.startswith('loyiha_'), state=Form.loyiha)
async def process_loyiha(call: types.CallbackQuery, state: FSMContext):
    loyiha = call.data[7:]
    if loyiha == 'Boshqa':
        await call.message.edit_text("<b>Loyiha nomini yozing:</b>")
        await Form.loyiha.set()
        await state.update_data(loyiha_manual=True)
    else:
        await state.update_data(loyiha=loyiha, loyiha_manual=False)
        await call.message.edit_text("<b>Summani kiriting:</b>")
        await Form.amount.set()
    await call.answer()

# Обработка ручного ввода Loyihalar
@dp.message_handler(state=Form.loyiha, content_types=types.ContentTypes.TEXT)
async def process_loyiha_manual(msg: types.Message, state: FSMContext):
    data = await state.get_data()
    if data.get('loyiha_manual'):
        await state.update_data(loyiha=msg.text.strip(), loyiha_manual=False)
        await msg.answer("<b>Summani kiriting:</b>")
        await Form.amount.set()

# Сумма
@dp.message_handler(lambda m: m.text.replace('.', '', 1).isdigit(), state=Form.amount)
async def process_amount(msg: types.Message, state: FSMContext):
    await state.update_data(amount=msg.text)
    await msg.answer("<b>To'lov turini tanlang:</b>", reply_markup=get_pay_types_kb())
    await Form.pay_type.set()

# Тип оплаты
@dp.callback_query_handler(lambda c: c.data.startswith('pay_'), state=Form.pay_type)
async def process_pay_type(call: types.CallbackQuery, state: FSMContext):
    pay = call.data[4:]
    await state.update_data(pay_type=pay)
    await call.message.edit_text("<b>Izoh kiriting (yoki пропустите):</b>", reply_markup=skip_kb)
    await Form.comment.set()
    await call.answer()

# Кнопка пропуска комментария
@dp.callback_query_handler(lambda c: c.data == 'skip_comment', state=Form.comment)
async def skip_comment_btn(call: types.CallbackQuery, state: FSMContext):
    await state.update_data(comment='-')
    data = await state.get_data()
    # Set and save the final timestamp
    data['dt'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    await state.update_data(dt=data['dt'])
    
    text = format_summary(data)
    
    await call.message.answer(text, reply_markup=confirm_kb)
    await state.set_state('confirm')
    await call.answer()

# Комментарий (или пропуск)
@dp.message_handler(state=Form.comment, content_types=types.ContentTypes.TEXT)
async def process_comment(msg: types.Message, state: FSMContext):
    await state.update_data(comment=msg.text)
    data = await state.get_data()
    # Set and save the final timestamp
    data['dt'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    await state.update_data(dt=data['dt'])
    
    text = format_summary(data)

    await msg.answer(text, reply_markup=confirm_kb)
    await state.set_state('confirm')

# Обработка кнопок Да/Нет
@dp.callback_query_handler(lambda c: c.data in ['confirm_yes', 'confirm_no'], state='confirm')
async def process_confirm(call: types.CallbackQuery, state: FSMContext):
    if call.data == 'confirm_yes':
        data = await state.get_data()
        from datetime import datetime
        dt = datetime.now()
        import platform
        if platform.system() == 'Windows':
            date_str = dt.strftime('%m/%d/%Y')
        else:
            date_str = dt.strftime('%-m/%-d/%Y')
        time_str = dt.strftime('%H:%M')
        data['dt_for_sheet'] = date_str
        data['vaqt'] = time_str
        # Гарантируем, что user_id всегда есть
        data['user_id'] = call.from_user.id
        try:
            add_to_google_sheet(data)
            await call.message.answer('✅ Данные успешно отправлены в Google Sheets!')

            # Уведомление для админов
            user_name = get_user_name(call.from_user.id) or call.from_user.full_name
            summary_text = format_summary(data)
            admin_notification_text = f"Foydalanuvchi <b>{user_name}</b> tomonidan kiritilgan yangi ma'lumot:\n\n{summary_text}"
            
            for admin_id in ADMINS:
                try:
                    await bot.send_message(admin_id, admin_notification_text)
                except Exception as e:
                    logging.error(f"Could not send notification to admin {admin_id}: {e}")

        except Exception as e:
            await call.message.answer(f'⚠️ Ошибка при отправке в Google Sheets: {e}')
        await state.finish()
    else:
        await call.message.answer('❌ Операция отменена.')
        await state.finish()
    # Возврат к стартовому шагу
    text = "<b>Qaysi turdagi operatsiya?</b>"
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton('🟢 Kirim', callback_data='type_kirim'),
        InlineKeyboardButton('🔴 Chiqim', callback_data='type_chiqim')
    )
    await call.message.answer(text, reply_markup=kb)
    await Form.type.set()
    await call.answer()

# --- Команды для админа ---
@dp.message_handler(commands=['add_tolov'], state='*')
async def add_paytype_cmd(msg: types.Message, state: FSMContext):
    if msg.from_user.id not in ADMINS:
        await msg.answer('Faqat admin uchun!')
        return
    await state.finish()  # Сброс состояния
    await msg.answer('Yangi To‘lov turi nomini yuboring:')
    await state.set_state('add_paytype')

@dp.message_handler(state='add_paytype', content_types=types.ContentTypes.TEXT)
async def add_paytype_save(msg: types.Message, state: FSMContext):
    name = msg.text.strip()
    conn = get_db_conn()
    c = conn.cursor()
    try:
        c.execute('INSERT INTO pay_types (name) VALUES (%s)', (name,))
        conn.commit()
        await msg.answer(f'✅ Yangi To‘lov turi qo‘shildi: {name}')
    except IntegrityError:
        await msg.answer('❗️ Bu nom allaqachon mavjud.')
        conn.rollback()
    conn.close()
    await state.finish()

@dp.message_handler(commands=['add_category'], state='*')
async def add_category_cmd(msg: types.Message, state: FSMContext):
    if msg.from_user.id not in ADMINS:
        await msg.answer('Faqat admin uchun!')
        return
    await state.finish()  # Сброс состояния
    await msg.answer('Yangi kategoriya nomini yuboring:')
    await state.set_state('add_category')

@dp.message_handler(state='add_category', content_types=types.ContentTypes.TEXT)
async def add_category_save(msg: types.Message, state: FSMContext):
    # Удаляем эмодзи из названия категории
    name = clean_emoji(msg.text.strip())
    conn = get_db_conn()
    c = conn.cursor()
    try:
        c.execute('INSERT INTO categories (name) VALUES (%s)', (name,))
        conn.commit()
        await msg.answer(f'✅ Yangi kategoriya qo‘shildi: {name}')
    except IntegrityError:
        await msg.answer('❗️ Bu nom allaqachon mavjud.')
        conn.rollback()
    conn.close()
    await state.finish()

# --- Удаление и изменение To'lov turi ---
@dp.message_handler(commands=['del_tolov'], state='*')
async def del_tolov_cmd(msg: types.Message, state: FSMContext):
    if msg.from_user.id not in ADMINS:
        await msg.answer('Faqat admin uchun!')
        return
    await state.finish()  # Сброс состояния
    kb = InlineKeyboardMarkup(row_width=1)
    for name in get_pay_types():
        kb.add(InlineKeyboardButton(f'❌ {name}', callback_data=f'del_tolov_{name}'))
    await msg.answer('O‘chirish uchun To‘lov turini tanlang:', reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith('del_tolov_'))
async def del_tolov_cb(call: types.CallbackQuery):
    if call.from_user.id not in ADMINS:
        await call.answer('Faqat admin uchun!', show_alert=True)
        return
    name = call.data[len('del_tolov_'):]
    conn = get_db_conn()
    c = conn.cursor()
    c.execute('DELETE FROM pay_types WHERE name=%s', (name,))
    conn.commit()
    conn.close()
    await call.message.edit_text(f'❌ To‘lov turi o‘chirildi: {name}')
    await call.answer()

@dp.message_handler(commands=['edit_tolov'], state='*')
async def edit_tolov_cmd(msg: types.Message, state: FSMContext):
    if msg.from_user.id not in ADMINS:
        await msg.answer('Faqat admin uchun!')
        return
    await state.finish()  # Сброс состояния
    kb = InlineKeyboardMarkup(row_width=1)
    for name in get_pay_types():
        kb.add(InlineKeyboardButton(f'✏️ {name}', callback_data=f'edit_tolov_{name}'))
    await msg.answer('Tahrirlash uchun To‘lov turini tanlang:', reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith('edit_tolov_'))
async def edit_tolov_cb(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMINS:
        await call.answer('Faqat admin uchun!', show_alert=True)
        return
    old_name = call.data[len('edit_tolov_'):]
    await state.update_data(edit_tolov_old=old_name)
    await call.message.answer(f'Yangi nomini yuboring (eski: {old_name}):')
    await state.set_state('edit_tolov_new')
    await call.answer()

@dp.message_handler(state='edit_tolov_new', content_types=types.ContentTypes.TEXT)
async def edit_tolov_save(msg: types.Message, state: FSMContext):
    data = await state.get_data()
    old_name = data.get('edit_tolov_old')
    new_name = msg.text.strip()
    conn = get_db_conn()
    c = conn.cursor()
    c.execute('UPDATE pay_types SET name=%s WHERE name=%s', (new_name, old_name))
    conn.commit()
    conn.close()
    await msg.answer(f'✏️ To‘lov turi o‘zgartirildi: {old_name} → {new_name}')
    await state.finish()

# --- Удаление и изменение Kotegoriyalar ---
@dp.message_handler(commands=['del_category'], state='*')
async def del_category_cmd(msg: types.Message, state: FSMContext):
    if msg.from_user.id not in ADMINS:
        await msg.answer('Faqat admin uchun!')
        return
    await state.finish()  # Сброс состояния
    kb = InlineKeyboardMarkup(row_width=1)
    for name in get_categories():
        kb.add(InlineKeyboardButton(f'❌ {name}', callback_data=f'del_category_{name}'))
    await msg.answer('O‘chirish uchun kategoriya tanlang:', reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith('del_category_'))
async def del_category_cb(call: types.CallbackQuery):
    if call.from_user.id not in ADMINS:
        await call.answer('Faqat admin uchun!', show_alert=True)
        return
    name = call.data[len('del_category_'):]
    conn = get_db_conn()
    c = conn.cursor()
    c.execute('DELETE FROM categories WHERE name=%s', (name,))
    conn.commit()
    conn.close()
    await call.message.edit_text(f'❌ Kategoriya o‘chirildi: {name}')
    await call.answer()

@dp.message_handler(commands=['edit_category'], state='*')
async def edit_category_cmd(msg: types.Message, state: FSMContext):
    if msg.from_user.id not in ADMINS:
        await msg.answer('Faqat admin uchun!')
        return
    await state.finish()  # Сброс состояния
    kb = InlineKeyboardMarkup(row_width=1)
    for name in get_categories():
        kb.add(InlineKeyboardButton(f'✏️ {name}', callback_data=f'edit_category_{name}'))
    await msg.answer('Tahrirlash uchun kategoriya tanlang:', reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith('edit_category_'))
async def edit_category_cb(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMINS:
        await call.answer('Faqat admin uchun!', show_alert=True)
        return
    old_name = call.data[len('edit_category_'):]
    await state.update_data(edit_category_old=old_name)
    await call.message.answer(f'Yangi nomini yuboring (eski: {old_name}):')
    await state.set_state('edit_category_new')
    await call.answer()

@dp.message_handler(state='edit_category_new', content_types=types.ContentTypes.TEXT)
async def edit_category_save(msg: types.Message, state: FSMContext):
    data = await state.get_data()
    old_name = data.get('edit_category_old')
    new_name = msg.text.strip()
    conn = get_db_conn()
    c = conn.cursor()
    c.execute('UPDATE categories SET name=%s WHERE name=%s', (new_name, old_name))
    conn.commit()
    conn.close()
    await msg.answer(f'✏️ Kategoriya o‘zgartirildi: {old_name} → {new_name}')
    await state.finish()

@dp.message_handler(commands=['userslist'], state='*')
async def users_list_cmd(msg: types.Message, state: FSMContext):
    if msg.from_user.id not in ADMINS:
        await msg.answer('Faqat admin uchun!')
        return
    await state.finish()  # Сброс состояния
    conn = get_db_conn()
    c = conn.cursor()
    c.execute("SELECT user_id, name, phone, reg_date FROM users WHERE status='approved'")
    rows = c.fetchall()
    conn.close()
    if not rows:
        await msg.answer('Hali birorta ham tasdiqlangan foydalanuvchi yo‘q.')
        return
    text = '<b>Tasdiqlangan foydalanuvchilar:</b>\n'
    for i, (user_id, name, phone, reg_date) in enumerate(rows, 1):
        text += f"\n{i}. <b>{name}</b>\nID: <code>{user_id}</code>\nTelefon: <code>{phone}</code>\nRo‘yxatdan o‘tgan: {reg_date}\n"
    await msg.answer(text)

@dp.message_handler(commands=['block_user'], state='*')
async def block_user_cmd(msg: types.Message, state: FSMContext):
    if msg.from_user.id not in ADMINS:
        await msg.answer('Faqat admin uchun!')
        return
    await state.finish()  # Сброс состояния
    conn = get_db_conn()
    c = conn.cursor()
    c.execute("SELECT user_id, name FROM users WHERE status='approved'")
    rows = c.fetchall()
    conn.close()
    if not rows:
        await msg.answer('Hali birorta ham tasdiqlangan foydalanuvchi yo‘q.')
        return
    kb = InlineKeyboardMarkup(row_width=1)
    for user_id, name in rows:
        kb.add(InlineKeyboardButton(f'🚫 {name} ({user_id})', callback_data=f'blockuser_{user_id}'))
    await msg.answer('Bloklash uchun foydalanuvchini tanlang:', reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith('blockuser_'))
async def block_user_cb(call: types.CallbackQuery):
    if call.from_user.id not in ADMINS:
        await call.answer('Faqat admin uchun!', show_alert=True)
        return
    user_id = int(call.data[len('blockuser_'):])
    update_user_status(user_id, 'denied')
    try:
        await bot.send_message(user_id, '❌ Sizga botdan foydalanishga ruxsat berilmagan. (Admin tomonidan bloklandi)')
    except Exception:
        pass
    await call.message.edit_text(f'🚫 Foydalanuvchi bloklandi: {user_id}')
    await call.answer()

@dp.message_handler(commands=['approve_user'], state='*')
async def approve_user_cmd(msg: types.Message, state: FSMContext):
    if msg.from_user.id not in ADMINS:
        await msg.answer('Faqat admin uchun!')
        return
    await state.finish()  # Сброс состояния
    conn = get_db_conn()
    c = conn.cursor()
    c.execute("SELECT user_id, name FROM users WHERE status='denied'")
    rows = c.fetchall()
    conn.close()
    if not rows:
        await msg.answer('Hali birorta ham bloklangan foydalanuvchi yo‘q.')
        return
    kb = InlineKeyboardMarkup(row_width=1)
    for user_id, name in rows:
        kb.add(InlineKeyboardButton(f'✅ {name} ({user_id})', callback_data=f'approveuser_{user_id}'))
    await msg.answer('Qayta tasdiqlash uchun foydalanuvchini tanlang:', reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith('approveuser_'))
async def approve_user_cb(call: types.CallbackQuery):
    if call.from_user.id not in ADMINS:
        await call.answer('Faqat admin uchun!', show_alert=True)
        return
    user_id = int(call.data[len('approveuser_'):])
    update_user_status(user_id, 'approved')
    try:
        await bot.send_message(user_id, '✅ Sizga botdan foydalanishga yana ruxsat berildi! /start')
    except Exception:
        pass
    await call.message.edit_text(f'✅ Foydalanuvchi qayta tasdiqlandi: {user_id}')
    await call.answer()

async def set_user_commands(dp):
    commands = [
        types.BotCommand("start", "Botni boshlash"),
        # Здесь можно добавить другие публичные команды
    ]
    await dp.bot.set_my_commands(commands)

async def notify_all_users(bot):
    conn = get_db_conn()
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE status='approved'")
    rows = c.fetchall()
    conn.close()
    for (user_id,) in rows:
        try:
            await bot.send_message(user_id, "Iltimos, /start ni bosing va botdan foydalanishni davom eting!")
        except Exception:
            pass  # Пользователь мог заблокировать бота или быть недоступен

if __name__ == '__main__':
    from aiogram import executor
    async def on_startup(dp):
        await set_user_commands(dp)
        await notify_all_users(dp.bot)
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup) 
