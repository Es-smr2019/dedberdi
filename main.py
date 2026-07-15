import asyncio
import logging
import os
import time
import random
import sqlite3
import threading
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

# Токен
TOKEN = "8987715811:AAHhMtYxhuKV3F5XtwPwm2PNzyfnW1RuZ1w"

bot = Bot(token=TOKEN)
dp = Dispatcher()
logging.basicConfig(level=logging.INFO)

DB_NAME = "bot_database.db"
COOLDOWN_SECONDS = 3.0

# ИСПОЛЬЗУЕМ RLock! Это исправляет зависание (deadlock) при выдаче админом!
db_lock = threading.RLock()

# --- ДОНАТ ПРЕДМЕТЫ (12 штук) ---
ITEMS = {
    1: {"name": "🪙 Двуликая монета", "desc": "Возврат ставки при проигрыше в /монета"},
    2: {"name": "🎲 Святые кости", "desc": "Возврат 50% ставки при неудаче в /кубик"},
    3: {"name": "🎰 Секрет казино", "desc": "Увеличивает выигрыш в /казино в 2 раза"},
    4: {"name": "🎯 Острый дротик", "desc": "Утешительный приз х1 при промахе в /дартс"},
    5: {"name": "🏀 Пружинистый мяч", "desc": "Бесплатная ставка в /баскет"},
    6: {"name": "💣 Радар сапера", "desc": "Игнорирует первый взрыв в /мины"},
    7: {"name": "💎 Кольцо жадности", "desc": "Умножает ЛЮБОЙ выигрыш на 1.5x"},
    8: {"name": "🛡 Щит неудачника", "desc": "Отменяет ЛЮБОЙ проигрыш (возврат ставки)"},
    9: {"name": "🏰 Флаг завоевателя", "desc": "Умножает добычу с Замка (x2)"},
    10: {"name": "⚔️ Зелье берсерка", "desc": "Гарантированная победа в Дуэли!"},
    11: {"name": "🕊 Белый флаг", "desc": "Сохраняет армию при поражении в набеге"},
    12: {"name": "⏳ Песочные часы", "desc": "Сбрасывает кулдаун на сбор ресурсов"}
}

# --- БАЗА ДАННЫХ И ИНИЦИАЛИЗАЦИЯ ---
def init_db():
    with db_lock:
        with sqlite3.connect(DB_NAME) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS users
                          (user_id INTEGER PRIMARY KEY, balance INTEGER, last_play REAL, incs INTEGER DEFAULT 0, active_item INTEGER DEFAULT 0)''')
            db.execute('''CREATE TABLE IF NOT EXISTS inventory
                          (user_id INTEGER, item_id INTEGER, quantity INTEGER, PRIMARY KEY (user_id, item_id))''')
            db.execute('''CREATE TABLE IF NOT EXISTS logs
                          (id INTEGER PRIMARY KEY AUTOINCREMENT, log_text TEXT)''')
            db.execute('''CREATE TABLE IF NOT EXISTS castles
                          (user_id INTEGER PRIMARY KEY, wood INTEGER DEFAULT 0, stone INTEGER DEFAULT 0, soldiers INTEGER DEFAULT 0, wall_level INTEGER DEFAULT 1, last_collect REAL DEFAULT 0)''')
            db.commit()

def add_log(text):
    with db_lock:
        with sqlite3.connect(DB_NAME) as db:
            db.execute("INSERT INTO logs (log_text) VALUES (?)", (text,))
            db.commit()

def register_user(user_id):
    with db_lock:
        with sqlite3.connect(DB_NAME) as db:
            db.execute("INSERT OR IGNORE INTO users (user_id, balance, last_play, incs, active_item) VALUES (?, 1000, 0, 0, 0)", (user_id,))
            db.execute("INSERT OR IGNORE INTO castles (user_id) VALUES (?)", (user_id,))
            db.commit()

def get_user(user_id):
    register_user(user_id)
    with db_lock:
        with sqlite3.connect(DB_NAME) as db:
            cursor = db.cursor()
            cursor.execute("SELECT balance, last_play, incs, active_item FROM users WHERE user_id = ?", (user_id,))
            return cursor.fetchone()

def process_bet(user_id, bet_str):
    if not bet_str or not bet_str.isdigit(): return False, 0, "⚠️ Ставка должна быть числом!", 0
    bet = int(bet_str)
    if bet <= 0: return False, 0, "⚠️ Ставка должна быть больше 0!", 0

    with db_lock:
        user = get_user(user_id)
        balance, last_play, active_item = user[0], user[1], user[3]
        
        if time.time() - last_play < COOLDOWN_SECONDS:
            return False, 0, "⏳ Подожди пару секунд!", 0
            
        actual_bet = 0 if active_item == 5 else bet # Пружинистый мяч
        if balance < actual_bet:
            return False, 0, f"❌ Мало монет! Баланс: <b>{balance}</b>", 0
        
        with sqlite3.connect(DB_NAME) as db:
            db.execute("UPDATE users SET balance = balance - ?, last_play = ?, active_item = 0 WHERE user_id = ?", (actual_bet, time.time(), user_id))
            db.commit()
        return True, bet, "", active_item

def add_balance(user_id, amount):
    with db_lock:
        with sqlite3.connect(DB_NAME) as db:
            db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
            db.commit()

# --- КЛАВИАТУРЫ ---
def get_main_menu():
    builder = ReplyKeyboardBuilder()
    builder.button(text="🎮 Игры")
    builder.button(text="🏰 Замок")
    builder.button(text="⚔️ Дуэль")
    builder.button(text="💼 Профиль")
    builder.button(text="🎒 Инвентарь")
    builder.button(text="📦 Кейс")
    builder.button(text="💸 Перевод")
    builder.adjust(3, 2, 2)
    return builder.as_markup(resize_keyboard=True)

def get_games_inline():
    builder = InlineKeyboardBuilder()
    builder.button(text="🪙 Монетка", switch_inline_query_current_chat="/м ")
    builder.button(text="🎲 Кубик", switch_inline_query_current_chat="/к ")
    builder.button(text="🎰 Казино", switch_inline_query_current_chat="/слоты ")
    builder.button(text="🎯 Дартс", switch_inline_query_current_chat="/д ")
    builder.button(text="🏀 Баскет", switch_inline_query_current_chat="/бс ")
    builder.button(text="💣 Мины", switch_inline_query_current_chat="/мины ")
    builder.adjust(2)
    return builder.as_markup()

# --- АДМИН ПАНЕЛЬ ---
def is_admin(message: types.Message):
    return message.from_user.username and message.from_user.username.lower() == "misedowner".lower()

@dp.message(Command("админ", "admin"))
async def cmd_admin(message: types.Message):
    if not is_admin(message): return
    await message.answer(
        "👑 <b>Панель Владельца</b>\n\n"
        "<code>/выдать валюту сумма [ID]</code>\n"
        "<code>/выдать инк сумма [ID]</code>\n"
        "<code>/логи</code> - операции", parse_mode="HTML"
    )

@dp.message(Command("выдать"))
async def cmd_give(message: types.Message, command: CommandObject):
    if not is_admin(message): return
    args = command.args
    if not args: return await message.answer("⚠️ Формат: /выдать валюту 1000")
    
    parts = args.split()
    if len(parts) < 2: return await message.answer("⚠️ Мало аргументов!")
    v_type, amount_str = parts[0].lower(), parts[1]
    if not amount_str.isdigit(): return await message.answer("⚠️ Сумма должна быть числом!")
    amount = int(amount_str)
    
    target_id = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else message.from_user.id
    register_user(target_id)
    
    with db_lock:
        with sqlite3.connect(DB_NAME) as db:
            if v_type == "валюту":
                db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, target_id))
                await message.answer(f"✅ Выдано {amount} монет пользователю {target_id}")
            elif v_type == "инк":
                db.execute("UPDATE users SET incs = incs + ? WHERE user_id = ?", (amount, target_id))
                await message.answer(f"✅ Выдано {amount} INCS пользователю {target_id}")
            db.commit()
        add_log(f"Админ выдал {amount} {v_type} -> ID {target_id}")

@dp.message(Command("логи", "logs"))
async def cmd_logs(message: types.Message):
    if not is_admin(message): return
    with db_lock:
        with sqlite3.connect(DB_NAME) as db:
            cursor = db.cursor()
            cursor.execute("SELECT log_text FROM logs ORDER BY id DESC LIMIT 10")
            rows = cursor.fetchall()
            text = "📜 <b>Логи:</b>\n" + "\n".join(f"• {r[0]}" for r in rows) if rows else "Пусто."
            await message.answer(text, parse_mode="HTML")

# --- СИСТЕМА ИНВЕНТАРЯ И КЕЙСОВ ---
@dp.message(F.text.in_(["📦 Кейс", "/кейс", "/case"]))
async def cmd_case(message: types.Message):
    user_id = message.from_user.id
    register_user(user_id)
    with db_lock:
        with sqlite3.connect(DB_NAME) as db:
            cursor = db.cursor()
            cursor.execute("SELECT incs FROM users WHERE user_id = ?", (user_id,))
            incs = cursor.fetchone()[0]
            if incs < 49: return await message.answer(f"❌ Нужно 49 INCS! У тебя <b>{incs}</b>.", parse_mode="HTML")
            
            db.execute("UPDATE users SET incs = incs - 49 WHERE user_id = ?", (user_id,))
            item_id = random.randint(1, 12)
            
            cursor.execute("SELECT quantity FROM inventory WHERE user_id = ? AND item_id = ?", (user_id, item_id))
            if cursor.fetchone(): db.execute("UPDATE inventory SET quantity = quantity + 1 WHERE user_id = ? AND item_id = ?", (user_id, item_id))
            else: db.execute("INSERT INTO inventory (user_id, item_id, quantity) VALUES (?, ?, 1)", (user_id, item_id))
            db.commit()
            
        item_name = ITEMS[item_id]["name"]
        add_log(f"Кейс: {user_id} получил {item_name}")
        await message.answer(f"📦 <b>Кейс открыт!</b> (-49 INCS)\n🎉 Выпал предмет: <b>{item_name}</b>!\nℹ️ <i>{ITEMS[item_id]['desc']}</i>", parse_mode="HTML")

@dp.message(F.text.in_(["🎒 Инвентарь", "/инвентарь", "/inv"]))
async def cmd_inventory(message: types.Message):
    user_id = message.from_user.id
    register_user(user_id)
    with db_lock:
        with sqlite3.connect(DB_NAME) as db:
            cursor = db.cursor()
            active_item = cursor.execute("SELECT active_item FROM users WHERE user_id = ?", (user_id,)).fetchone()[0]
            inv = cursor.execute("SELECT item_id, quantity FROM inventory WHERE user_id = ? AND quantity > 0", (user_id,)).fetchall()
            
            text = "🎒 <b>Инвентарь:</b>\n\n"
            if active_item: text += f"🟢 <b>Надето:</b> {ITEMS[active_item]['name']}\n\n"
            if not inv: return await message.answer(text + "<i>Пусто. Открой кейс!</i>", parse_mode="HTML")
                
            builder = InlineKeyboardBuilder()
            for item_id, qty in inv:
                name = ITEMS[item_id]['name']
                text += f"• <b>{name}</b> (x{qty})\n  └ <i>{ITEMS[item_id]['desc']}</i>\n"
                builder.button(text=f"Надеть {name.split()[0]}", callback_data=f"eq_{item_id}")
            builder.adjust(2)
            await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data.startswith("eq_"))
async def equip_callback(callback: types.CallbackQuery):
    user_id, item_id = callback.from_user.id, int(callback.data.split("_")[1])
    with db_lock:
        with sqlite3.connect(DB_NAME) as db:
            qty = db.execute("SELECT quantity FROM inventory WHERE user_id = ? AND item_id = ?", (user_id, item_id)).fetchone()
            if not qty or qty[0] <= 0: return await callback.answer("Нет предмета!", show_alert=True)
                
            current = db.execute("SELECT active_item FROM users WHERE user_id = ?", (user_id,)).fetchone()[0]
            if current != 0: db.execute("UPDATE inventory SET quantity = quantity + 1 WHERE user_id = ? AND item_id = ?", (user_id, current))
            
            db.execute("UPDATE inventory SET quantity = quantity - 1 WHERE user_id = ? AND item_id = ?", (user_id, item_id))
            db.execute("UPDATE users SET active_item = ? WHERE user_id = ?", (item_id, user_id))
            db.commit()
    await callback.message.delete()
    await callback.message.answer(f"✅ Надет: <b>{ITEMS[item_id]['name']}</b>", parse_mode="HTML")

# --- СТАБИЛЬНЫЙ И УДОБНЫЙ ПЕРЕВОД ---
@dp.message(F.text == "💸 Перевод")
async def btn_transfer(message: types.Message):
    await message.answer("💸 <b>Как перевести деньги:</b>\nПросто ответьте (сделайте Reply) на сообщение игрока в чате и напишите сумму с плюсом: <code>+500</code>", parse_mode="HTML")

@dp.message(Command("перевод", "pay"))
async def cmd_transfer(message: types.Message, command: CommandObject):
    args = command.args
    if not args: return await message.answer("⚠️ Ответь на сообщение игрока: /перевод 500")
    if not args.split()[0].isdigit(): return await message.answer("⚠️ Сумма должна быть числом!")
    amount = int(args.split()[0])
    
    target_id = message.reply_to_message.from_user.id if message.reply_to_message else None
    if len(args.split()) > 1 and args.split()[1].isdigit(): target_id = int(args.split()[1])
    if not target_id: return await message.answer("⚠️ Ответь на сообщение игрока!")
    await execute_transfer(message, message.from_user.id, target_id, amount)

@dp.message(F.reply_to_message & F.text)
async def quick_transfer(message: types.Message):
    text = message.text.strip()
    if text.startswith("+") and text[1:].isdigit():
        await execute_transfer(message, message.from_user.id, message.reply_to_message.from_user.id, int(text[1:]))

async def execute_transfer(message, from_id, to_id, amount):
    if from_id == to_id: return await message.answer("⚠️ Нельзя перевести себе!")
    if amount <= 0: return await message.answer("⚠️ Сумма > 0!")
    
    register_user(from_id); register_user(to_id)
    with db_lock:
        with sqlite3.connect(DB_NAME) as db:
            balance = db.execute("SELECT balance FROM users WHERE user_id = ?", (from_id,)).fetchone()[0]
            if balance < amount: return await message.answer(f"❌ Мало средств! У тебя {balance}")
                
            db.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, from_id))
            db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, to_id))
            db.commit()
    add_log(f"Перевод: {from_id} -> {to_id} ({amount})")
    await message.answer(f"✅ Перевод <b>{amount}</b> 💰 успешен!", parse_mode="HTML")

# --- КОМАНДЫ (АЛИАСЫ) ---
@dp.message(Command("start", "старт"))
async def cmd_start(message: types.Message):
    register_user(message.from_user.id)
    await message.answer("🎉 Добро пожаловать! Выбери действие в меню ниже:", reply_markup=get_main_menu())

@dp.message(F.text.in_(["💼 Профиль", "/профиль", "/баланс", "/б", "/bal"]))
async def cmd_profile(message: types.Message):
    user = get_user(message.from_user.id)
    await message.answer(f"👤 <b>Профиль:</b>\n💰 Монеты: <b>{user[0]}</b>\n💎 INCS: <b>{user[2]}</b>", parse_mode="HTML")

@dp.message(F.text == "🎮 Игры")
async def cmd_games(message: types.Message):
    await message.answer("🕹 Выбери игру (нажми и введи ставку):", reply_markup=get_games_inline())

# --- ПРОСТЫЕ ИГРЫ ---
@dp.message(Command("монета", "м", "flip"))
async def play_flip(message: types.Message, command: CommandObject):
    if not command.args: return await message.answer("⚠️ Формат: /м 100 орел")
    parts = command.args.split()
    if len(parts) != 2 or parts[1].lower() not in ["орел", "решка"]: return await message.answer("⚠️ Формат: /м 100 орел")
    
    ok, bet, err, item = process_bet(message.from_user.id, parts[0])
    if not ok: return await message.answer(err)

    choice, result_str = parts[1].lower(), "орел" if random.choice([True, False]) else "решка"
    if choice == result_str:
        win = int(bet * 2 * (1.5 if item == 7 else 1))
        add_balance(message.from_user.id, win)
        await message.answer(f"🪙 <b>{result_str}</b>! Выиграл <b>{win}</b>", parse_mode="HTML")
    else:
        if item in [1, 8]: add_balance(message.from_user.id, bet); await message.answer("🛡 Предмет спас ставку!")
        else: await message.answer(f"🪙 <b>{result_str}</b>. Проиграл <b>{bet}</b>", parse_mode="HTML")

@dp.message(Command("кубик", "к", "dice"))
async def play_dice(message: types.Message, command: CommandObject):
    ok, bet, err, item = process_bet(message.from_user.id, command.args)
    if not ok: return await message.answer(err)
    msg = await message.answer_dice(emoji="🎲"); await asyncio.sleep(3)
    val = msg.dice.value
    if val >= 5:
        win = int(bet * 2 * (1.5 if item == 7 else 1))
        add_balance(message.from_user.id, win); await message.answer(f"🎲 <b>{val}</b>! Выиграл <b>{win}</b>", parse_mode="HTML")
    else:
        if item == 8: add_balance(message.from_user.id, bet); await message.answer("🛡 Щит спас!")
        elif item == 2: add_balance(message.from_user.id, bet//2); await message.answer("🎲 Кости вернули 50%!")
        else: await message.answer(f"🎲 <b>{val}</b>. Проиграл <b>{bet}</b>", parse_mode="HTML")

@dp.message(Command("казино", "слоты", "slots"))
async def play_slots(message: types.Message, command: CommandObject):
    ok, bet, err, item = process_bet(message.from_user.id, command.args)
    if not ok: return await message.answer(err)
    msg = await message.answer_dice(emoji="🎰"); await asyncio.sleep(2)
    val = msg.dice.value
    if val in [64, 1, 22, 43]:
        mult = 10 if val == 64 else 3
        win = int(bet * mult * (2 if item == 3 else 1) * (1.5 if item == 7 else 1))
        add_balance(message.from_user.id, win); await message.answer(f"🎰 Победа! Выиграл <b>{win}</b>", parse_mode="HTML")
    else:
        if item == 8: add_balance(message.from_user.id, bet); await message.answer("🛡 Щит спас!")
        else: await message.answer(f"🎰 Мимо. Проиграл <b>{bet}</b>", parse_mode="HTML")

# --- БОЛЬШАЯ ИГРА 1: 🏰 ЗАМОК (Мультиплеер) ---
@dp.message(F.text.in_(["🏰 Замок", "/замок", "/castle"]))
async def cmd_castle(message: types.Message):
    user_id = message.from_user.id
    register_user(user_id)
    with db_lock:
        with sqlite3.connect(DB_NAME) as db:
            c = db.execute("SELECT wood, stone, soldiers, wall_level FROM castles WHERE user_id = ?", (user_id,)).fetchone()
            
    text = (f"🏰 <b>Твой Замок</b>\n\n"
            f"🪵 Дерево: <b>{c[0]}</b>\n"
            f"🪨 Камень: <b>{c[1]}</b>\n"
            f"💂‍♂️ Солдаты: <b>{c[2]}</b>\n"
            f"🧱 Уровень стены: <b>{c[3]}</b>\n\n"
            f"<i>💡 Нанимай солдат для набегов на других игроков: ответь на их сообщение /набег</i>")
            
    b = InlineKeyboardBuilder()
    b.button(text="⛏ Сбор ресурсов", callback_data="c_farm")
    b.button(text="💂‍♂️ Нанять 10 солдат (100💰)", callback_data="c_army")
    b.button(text="🧱 Улучшить стену (50🪵 50🪨)", callback_data="c_wall")
    b.adjust(1)
    await message.answer(text, reply_markup=b.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data.startswith("c_"))
async def castle_callbacks(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    action = callback.data.split("_")[1]
    
    with db_lock:
        with sqlite3.connect(DB_NAME) as db:
            user = db.execute("SELECT balance, active_item FROM users WHERE user_id = ?", (user_id,)).fetchone()
            c = db.execute("SELECT wood, stone, soldiers, wall_level, last_collect FROM castles WHERE user_id = ?", (user_id,)).fetchone()
            bal, item = user[0], user[1]
            w, s, sol, wall, last = c
            
            if action == "farm":
                if time.time() - last < 60 and item != 12:
                    return await callback.answer(f"⏳ Ресурсы копятся. Жди {int(60 - (time.time() - last))} сек.", show_alert=True)
                
                wood_g, stone_g = random.randint(10, 30), random.randint(10, 30)
                if item == 9: wood_g *= 2; stone_g *= 2 # Флаг завоевателя
                
                db.execute("UPDATE castles SET wood = wood + ?, stone = stone + ?, last_collect = ? WHERE user_id = ?", (wood_g, stone_g, time.time(), user_id))
                if item == 12: db.execute("UPDATE users SET active_item = 0 WHERE user_id = ?", (user_id,))
                db.commit()
                await callback.message.delete()
                await callback.message.answer(f"⛏ Добыто: <b>{wood_g}</b> 🪵 и <b>{stone_g}</b> 🪨", parse_mode="HTML")
                
            elif action == "army":
                if bal < 100: return await callback.answer("❌ Нужно 100 монет!", show_alert=True)
                db.execute("UPDATE users SET balance = balance - 100 WHERE user_id = ?", (user_id,))
                db.execute("UPDATE castles SET soldiers = soldiers + 10 WHERE user_id = ?", (user_id,))
                db.commit()
                await callback.answer("✅ Нанято 10 солдат!", show_alert=True)
                await cmd_castle(callback.message)
                await callback.message.delete()
                
            elif action == "wall":
                if w < 50 or s < 50: return await callback.answer("❌ Нужно 50 дерева и 50 камня!", show_alert=True)
                db.execute("UPDATE castles SET wood = wood - 50, stone = stone - 50, wall_level = wall_level + 1 WHERE user_id = ?", (user_id,))
                db.commit()
                await callback.answer("✅ Стена улучшена!", show_alert=True)
                await cmd_castle(callback.message)
                await callback.message.delete()

@dp.message(Command("набег", "raid"))
async def cmd_raid(message: types.Message):
    if not message.reply_to_message: return await message.answer("⚠️ Ответь на сообщение игрока для набега!")
    atk_id, def_id = message.from_user.id, message.reply_to_message.from_user.id
    if atk_id == def_id: return await message.answer("⚠️ Нельзя напасть на себя!")
    
    register_user(atk_id); register_user(def_id)
    with db_lock:
        with sqlite3.connect(DB_NAME) as db:
            atk_item = db.execute("SELECT active_item FROM users WHERE user_id = ?", (atk_id,)).fetchone()[0]
            atk_c = db.execute("SELECT soldiers FROM castles WHERE user_id = ?", (atk_id,)).fetchone()
            def_c = db.execute("SELECT wood, stone, soldiers, wall_level FROM castles WHERE user_id = ?", (def_id,)).fetchone()
            
            if atk_c[0] < 10: return await message.answer("❌ Для набега нужно минимум 10 солдат!")
            
            atk_power = atk_c[0] * random.uniform(0.8, 1.2)
            def_power = (def_c[2] + def_c[3] * 5) * random.uniform(0.8, 1.2)
            
            if atk_power > def_power: # Победа
                steal_w, steal_s = int(def_c[0] * 0.3), int(def_c[1] * 0.3)
                if atk_item == 9: steal_w *= 2; steal_s *= 2 # Флаг
                
                db.execute("UPDATE castles SET wood = wood - ?, stone = stone - ?, soldiers = MAX(0, soldiers - ?) WHERE user_id = ?", (steal_w, steal_s, int(def_c[2]*0.5), def_id))
                db.execute("UPDATE castles SET wood = wood + ?, stone = stone + ?, soldiers = MAX(0, soldiers - ?) WHERE user_id = ?", (steal_w, steal_s, int(atk_c[0]*0.1), atk_id))
                db.commit()
                await message.answer(f"⚔️ <b>УСПЕШНЫЙ НАБЕГ!</b>\nТы пробил стену и украл <b>{steal_w}🪵</b> и <b>{steal_s}🪨</b>!", parse_mode="HTML")
            else: # Поражение
                lost = int(atk_c[0] * 0.5) if atk_item != 11 else 0 # Белый флаг спасает
                if atk_item == 11: db.execute("UPDATE users SET active_item = 0 WHERE user_id = ?", (atk_id,))
                
                db.execute("UPDATE castles SET soldiers = MAX(0, soldiers - ?) WHERE user_id = ?", (lost, atk_id))
                db.commit()
                text = "⚔️ <b>ПОРАЖЕНИЕ!</b>\nЗащита оказалась сильнее."
                if atk_item == 11: text += " 🕊 Белый флаг спас армию!"
                else: text += f" Потери: <b>{lost}</b> солдат."
                await message.answer(text, parse_mode="HTML")

# --- БОЛЬШАЯ ИГРА 2: ⚔️ ДУЭЛЬ (Мультиплеер) ---
duels = {}

@dp.message(F.text == "⚔️ Дуэль")
async def btn_duel_info(message: types.Message):
    await message.answer("⚔️ <b>Как вызвать на дуэль:</b>\nОтветьте на сообщение игрока: <code>/дуэль 500</code>\n(Победитель забирает весь банк!)", parse_mode="HTML")

@dp.message(Command("дуэль", "duel"))
async def cmd_duel(message: types.Message, command: CommandObject):
    if not message.reply_to_message: return await message.answer("⚠️ Ответь на сообщение игрока!")
    atk_id, def_id = message.from_user.id, message.reply_to_message.from_user.id
    if atk_id == def_id: return await message.answer("⚠️ Нельзя вызвать самого себя!")
    
    if not command.args or not command.args.isdigit(): return await message.answer("⚠️ Укажи ставку: /дуэль 100")
    bet = int(command.args)
    
    ok, _, err, atk_item = process_bet(atk_id, str(bet))
    if not ok: return await message.answer(err)
    
    duel_id = random.randint(1000, 9999)
    duels[duel_id] = {"atk": atk_id, "def": def_id, "bet": bet, "atk_item": atk_item}
    
    b = InlineKeyboardBuilder()
    b.button(text="⚔️ Принять бой", callback_data=f"duel_acc_{duel_id}")
    b.button(text="❌ Отказаться", callback_data=f"duel_dec_{duel_id}")
    await message.answer(f"⚔️ Игрок вызывает тебя на дуэль!\n💰 Ставка: <b>{bet}</b>\n(Нажми кнопку чтобы ответить)", reply_markup=b.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data.startswith("duel_"))
async def duel_callback(callback: types.CallbackQuery):
    action, duel_id = callback.data.split("_")[1], int(callback.data.split("_")[2])
    if duel_id not in duels: return await callback.answer("Дуэль устарела!", show_alert=True)
    duel = duels[duel_id]
    
    if callback.from_user.id != duel["def"]: return await callback.answer("Это не тебе!", show_alert=True)
    
    if action == "dec":
        add_balance(duel["atk"], duel["bet"]) # Возврат ставки
        del duels[duel_id]
        return await callback.message.edit_text("❌ Дуэль отклонена. Ставка возвращена.")
        
    # Принятие дуэли
    ok, _, err, def_item = process_bet(duel["def"], str(duel["bet"]))
    if not ok: return await callback.answer("❌ У тебя не хватает монет на ставку!", show_alert=True)
    
    del duels[duel_id]
    await callback.message.edit_text("⚔️ Дуэль началась! Бросаем кубики...")
    await asyncio.sleep(2)
    
    # Расчет победителя
    atk_roll, def_roll = random.randint(1, 100), random.randint(1, 100)
    if duel["atk_item"] == 10: atk_roll = 999 # Зелье берсерка
    if def_item == 10: def_roll = 999
    
    pot = duel["bet"] * 2
    if atk_roll > def_roll:
        add_balance(duel["atk"], pot)
        txt = f"🏆 <b>Победа Вызывающего!</b>\nОн забрал банк: <b>{pot}</b>💰"
    elif def_roll > atk_roll:
        add_balance(duel["def"], pot)
        txt = f"🏆 <b>Победа Защитника!</b>\nОн забрал банк: <b>{pot}</b>💰"
    else:
        add_balance(duel["atk"], duel["bet"]); add_balance(duel["def"], duel["bet"])
        txt = "🤝 <b>Ничья!</b> Ставки возвращены."
        
    await callback.message.edit_text(txt, parse_mode="HTML")

async def main():
    init_db()
    await bot.delete_webhook(drop_pending_updates=True) 
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
