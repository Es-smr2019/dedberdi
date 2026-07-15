import asyncio
import logging
import os
import time
import random
import sqlite3
import threading
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Токен, который ты просил указать напрямую
TOKEN = "8987715811:AAHhMtYxhuKV3F5XtwPwm2PNzyfnW1RuZ1w"

bot = Bot(token=TOKEN)
dp = Dispatcher()
logging.basicConfig(level=logging.INFO)

DB_NAME = "bot_database.db"
COOLDOWN_SECONDS = 3.0 # Сделал кулдаун чуть меньше для удобства

db_lock = threading.Lock()

# --- ДОНАТ ПРЕДМЕТЫ (8 штук) ---
ITEMS = {
    1: {"name": "🪙 Двуликая монета", "desc": "Возврат ставки при проигрыше в /монета"},
    2: {"name": "🎲 Святые кости", "desc": "Возврат 50% ставки при неудаче в /кубик"},
    3: {"name": "🎰 Секрет казино", "desc": "Увеличивает выигрыш в /казино в 2 раза"},
    4: {"name": "🎯 Острый дротик", "desc": "Утешительный приз х1 при промахе в /дартс"},
    5: {"name": "🏀 Пружинистый мяч", "desc": "Бесплатная ставка в /баскет (0 списания)"},
    6: {"name": "💣 Радар сапера", "desc": "Игнорирует первый взрыв в /мины"},
    7: {"name": "💎 Кольцо жадности", "desc": "Умножает ЛЮБОЙ выигрыш на 1.5x"},
    8: {"name": "🛡 Щит неудачника", "desc": "Отменяет ЛЮБОЙ проигрыш (возврат ставки)"}
}

# --- БАЗА ДАННЫХ И ИНИЦИАЛИЗАЦИЯ ---
def init_db():
    with db_lock:
        with sqlite3.connect(DB_NAME) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS users
                          (user_id INTEGER PRIMARY KEY, balance INTEGER, last_play REAL)''')
            # Пытаемся добавить новые колонки (если они уже есть - проигнорируется)
            try: db.execute("ALTER TABLE users ADD COLUMN incs INTEGER DEFAULT 0")
            except: pass
            try: db.execute("ALTER TABLE users ADD COLUMN active_item INTEGER DEFAULT 0")
            except: pass
            
            db.execute('''CREATE TABLE IF NOT EXISTS inventory
                          (user_id INTEGER, item_id INTEGER, quantity INTEGER, PRIMARY KEY (user_id, item_id))''')
            db.execute('''CREATE TABLE IF NOT EXISTS logs
                          (id INTEGER PRIMARY KEY AUTOINCREMENT, log_text TEXT)''')
            db.commit()

def add_log(text):
    with db_lock:
        with sqlite3.connect(DB_NAME) as db:
            db.execute("INSERT INTO logs (log_text) VALUES (?)", (text,))
            db.commit()

def get_user(user_id):
    with db_lock:
        with sqlite3.connect(DB_NAME) as db:
            cursor = db.cursor()
            cursor.execute("SELECT balance, last_play, incs, active_item FROM users WHERE user_id = ?", (user_id,))
            return cursor.fetchone()

def register_user(user_id):
    with db_lock:
        with sqlite3.connect(DB_NAME) as db:
            db.execute("INSERT OR IGNORE INTO users (user_id, balance, last_play, incs, active_item) VALUES (?, ?, ?, ?, ?)", 
                       (user_id, 1000, 0, 0, 0))
            db.commit()

def process_bet(user_id, bet_str):
    if not bet_str or not bet_str.isdigit():
        return False, 0, "⚠️ Ставка должна быть целым числом!", 0
    bet = int(bet_str)
    if bet <= 0:
        return False, 0, "⚠️ Ставка должна быть больше нуля!", 0

    with db_lock:
        with sqlite3.connect(DB_NAME) as db:
            cursor = db.cursor()
            cursor.execute("SELECT balance, last_play, active_item FROM users WHERE user_id = ?", (user_id,))
            user = cursor.fetchone()
            
            if not user:
                return False, 0, "❌ Напиши /старт", 0
                
            balance, last_play, active_item = user
            if time.time() - last_play < COOLDOWN_SECONDS:
                return False, 0, "⏳ Подожди пару секунд!", 0
                
            actual_bet = bet
            if active_item == 5: # Пружинистый мяч делает ставку бесплатной
                actual_bet = 0

            if balance < actual_bet:
                return False, 0, f"❌ Недостаточно монет! Баланс: <b>{balance}</b> 💰", 0
            
            # Списываем ставку и очищаем активный предмет
            db.execute("UPDATE users SET balance = balance - ?, last_play = ?, active_item = 0 WHERE user_id = ?", 
                       (actual_bet, time.time(), user_id))
            db.commit()
            return True, bet, "", active_item

def add_balance(user_id, amount):
    with db_lock:
        with sqlite3.connect(DB_NAME) as db:
            db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
            db.commit()

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
        "<code>/логи</code> - последние 10 операций\n"
        "<i>Если не указать ID, выдастся тебе.</i>", parse_mode="HTML"
    )

@dp.message(Command("выдать"))
async def cmd_give(message: types.Message, command: CommandObject):
    if not is_admin(message): return
    args = command.args
    if not args: return await message.answer("⚠️ Формат: /выдать валюту 1000  ИЛИ  /выдать инк 50")
    
    parts = args.split()
    if len(parts) < 2: return await message.answer("⚠️ Мало аргументов!")
    
    v_type = parts[0].lower()
    if not parts[1].isdigit(): return await message.answer("⚠️ Сумма должна быть числом!")
    amount = int(parts[1])
    
    target_id = message.from_user.id
    if len(parts) >= 3 and parts[2].isdigit():
        target_id = int(parts[2])

    register_user(target_id)
    with db_lock:
        with sqlite3.connect(DB_NAME) as db:
            if v_type == "валюту":
                db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, target_id))
                await message.answer(f"✅ Выдано {amount} монет пользователю {target_id}")
                add_log(f"Админ выдал {amount} монет -> ID {target_id}")
            elif v_type == "инк":
                db.execute("UPDATE users SET incs = incs + ? WHERE user_id = ?", (amount, target_id))
                await message.answer(f"✅ Выдано {amount} INCS пользователю {target_id}")
                add_log(f"Админ выдал {amount} INCS -> ID {target_id}")
            else:
                await message.answer("⚠️ Укажи 'валюту' или 'инк'")
            db.commit()

@dp.message(Command("логи", "logs"))
async def cmd_logs(message: types.Message):
    if not is_admin(message): return
    with db_lock:
        with sqlite3.connect(DB_NAME) as db:
            cursor = db.cursor()
            cursor.execute("SELECT log_text FROM logs ORDER BY id DESC LIMIT 10")
            rows = cursor.fetchall()
            if not rows: return await message.answer("Логи пусты.")
            text = "📜 <b>Последние логи:</b>\n" + "\n".join(f"• {r[0]}" for r in rows)
            await message.answer(text, parse_mode="HTML")

# --- СИСТЕМА ИНВЕНТАРЯ И КЕЙСОВ ---
@dp.message(Command("кейс", "case"))
async def cmd_case(message: types.Message):
    user_id = message.from_user.id
    register_user(user_id)
    with db_lock:
        with sqlite3.connect(DB_NAME) as db:
            cursor = db.cursor()
            cursor.execute("SELECT incs FROM users WHERE user_id = ?", (user_id,))
            incs = cursor.fetchone()[0]
            
            if incs < 49:
                return await message.answer(f"❌ Недостаточно INCS! Нужно 49, а у тебя <b>{incs}</b>.\n💎 <i>INCS - это донат валюта.</i>", parse_mode="HTML")
            
            db.execute("UPDATE users SET incs = incs - 49 WHERE user_id = ?", (user_id,))
            
            # Выпадение предмета
            item_id = random.randint(1, 8)
            cursor.execute("SELECT quantity FROM inventory WHERE user_id = ? AND item_id = ?", (user_id, item_id))
            row = cursor.fetchone()
            if row:
                db.execute("UPDATE inventory SET quantity = quantity + 1 WHERE user_id = ? AND item_id = ?", (user_id, item_id))
            else:
                db.execute("INSERT INTO inventory (user_id, item_id, quantity) VALUES (?, ?, 1)", (user_id, item_id))
            db.commit()
            
            item_name = ITEMS[item_id]["name"]
            add_log(f"ID {user_id} открыл кейс и получил {item_name}")
            await message.answer(f"📦 <b>Кейс открыт!</b> (-49 INCS)\n\n🎉 Тебе выпал предмет: <b>{item_name}</b>!\nℹ️ <i>{ITEMS[item_id]['desc']}</i>\n\nИспользуй /инвентарь чтобы применить.", parse_mode="HTML")

@dp.message(Command("инвентарь", "inv"))
async def cmd_inventory(message: types.Message):
    user_id = message.from_user.id
    register_user(user_id)
    with db_lock:
        with sqlite3.connect(DB_NAME) as db:
            cursor = db.cursor()
            cursor.execute("SELECT active_item FROM users WHERE user_id = ?", (user_id,))
            active_item = cursor.fetchone()[0]
            
            cursor.execute("SELECT item_id, quantity FROM inventory WHERE user_id = ? AND quantity > 0", (user_id,))
            inv = cursor.fetchall()
            
            text = "🎒 <b>Твой инвентарь:</b>\n\n"
            if active_item != 0:
                text += f"🟢 <b>Экипировано:</b> {ITEMS[active_item]['name']}\n<i>Действует на следующую игру.</i>\n\n"
            
            if not inv:
                text += "<i>Пусто. Открой /кейс за 49 INCS!</i>"
                return await message.answer(text, parse_mode="HTML")
                
            builder = InlineKeyboardBuilder()
            for item_id, qty in inv:
                name = ITEMS[item_id]['name']
                text += f"• <b>{name}</b> (x{qty})\n  └ <i>{ITEMS[item_id]['desc']}</i>\n"
                builder.button(text=f"Надеть {name.split()[0]}", callback_data=f"equip_{item_id}")
            
            builder.adjust(2)
            await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data.startswith("equip_"))
async def equip_callback(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    item_id = int(callback.data.split("_")[1])
    
    with db_lock:
        with sqlite3.connect(DB_NAME) as db:
            cursor = db.cursor()
            # Проверяем наличие предмета
            cursor.execute("SELECT quantity FROM inventory WHERE user_id = ? AND item_id = ?", (user_id, item_id))
            row = cursor.fetchone()
            if not row or row[0] <= 0:
                return await callback.answer("У тебя нет этого предмета!", show_alert=True)
                
            # Проверяем что сейчас надето
            cursor.execute("SELECT active_item FROM users WHERE user_id = ?", (user_id,))
            current_active = cursor.fetchone()[0]
            if current_active != 0:
                # Возвращаем старый в инвентарь
                db.execute("UPDATE inventory SET quantity = quantity + 1 WHERE user_id = ? AND item_id = ?", (user_id, current_active))
            
            # Списываем новый и надеваем
            db.execute("UPDATE inventory SET quantity = quantity - 1 WHERE user_id = ? AND item_id = ?", (user_id, item_id))
            db.execute("UPDATE users SET active_item = ? WHERE user_id = ?", (item_id, user_id))
            db.commit()
            
    await callback.message.delete()
    await callback.message.answer(f"✅ Предмет <b>{ITEMS[item_id]['name']}</b> активирован на следующую игру!", parse_mode="HTML")
    await callback.answer()

# --- СТАБИЛЬНЫЙ ПЕРЕВОД ---
@dp.message(Command("перевод", "pay"))
async def cmd_transfer(message: types.Message, command: CommandObject):
    args = command.args
    if not args: return await message.answer("⚠️ Формат: /перевод [сумма] [ID] (или в ответ на сообщение)")
    
    parts = args.split()
    if not parts[0].isdigit(): return await message.answer("⚠️ Сумма должна быть числом!")
    amount = int(parts[0])
    
    target_id = None
    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
    elif len(parts) > 1 and parts[1].isdigit():
        target_id = int(parts[1])
        
    if not target_id: return await message.answer("⚠️ Укажи ID или ответь на сообщение!")
    await execute_transfer(message, message.from_user.id, target_id, amount)

# Альтернативный перевод просто плюсом на реплай
@dp.message(F.reply_to_message & F.text)
async def quick_transfer(message: types.Message):
    text = message.text.strip()
    if text.startswith("+") and text[1:].isdigit():
        amount = int(text[1:])
        target_id = message.reply_to_message.from_user.id
        await execute_transfer(message, message.from_user.id, target_id, amount)

async def execute_transfer(message, from_id, to_id, amount):
    if from_id == to_id: return await message.answer("⚠️ Нельзя переводить себе!")
    if amount <= 0: return await message.answer("⚠️ Сумма должна быть больше 0!")
    
    register_user(from_id)
    register_user(to_id)
    
    with db_lock:
        with sqlite3.connect(DB_NAME) as db:
            cursor = db.cursor()
            cursor.execute("SELECT balance FROM users WHERE user_id = ?", (from_id,))
            balance = cursor.fetchone()[0]
            if balance < amount:
                return await message.answer(f"❌ Недостаточно средств! У тебя {balance}")
                
            db.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, from_id))
            db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, to_id))
            db.commit()
            add_log(f"Перевод: {from_id} -> {to_id} ({amount} монет)")
            await message.answer(f"✅ Успешный перевод! <b>{amount}</b> 💰 отправлено.", parse_mode="HTML")

# --- КОМАНДЫ ---
@dp.message(Command("start", "старт"))
async def cmd_start(message: types.Message):
    register_user(message.from_user.id)
    # Исправлена ошибка HTML: удалены символы '<' и '>' внутри текста
    await message.answer(
        "🎉 Добро пожаловать!\n"
        "🎮 <b>Игры:</b> /монета, /кубик, /казино, /дартс, /баскет, /мины\n"
        "💸 <b>Перевод:</b> /перевод сумма ID\n"
        "💼 <b>Профиль:</b> /профиль, /инвентарь\n"
        "📦 <b>Донат:</b> /кейс (49 INCS)", parse_mode="HTML"
    )

@dp.message(Command("профиль", "баланс"))
async def cmd_profile(message: types.Message):
    user = get_user(message.from_user.id)
    if user:
        await message.answer(f"👤 <b>Профиль:</b>\n💰 Монеты: <b>{user[0]}</b>\n💎 INCS: <b>{user[2]}</b>\n\n🎒 <i>Используй /инвентарь для предметов</i>", parse_mode="HTML")

# --- ИГРЫ (С ПОДДЕРЖКОЙ ПРЕДМЕТОВ) ---
@dp.message(Command("монета", "flip"))
async def play_flip(message: types.Message, command: CommandObject):
    if not command.args: return await message.answer("⚠️ Формат: /монета [ставка] [орел/решка]")
    parts = command.args.split()
    if len(parts) != 2 or parts[1].lower() not in ["орел", "решка"]: return await message.answer("⚠️ Формат: /монета [ставка] [орел/решка]")
    choice = parts[1].lower()

    ok, bet, err, item = process_bet(message.from_user.id, parts[0])
    if not ok: return await message.answer(err)

    is_heads = random.choice([True, False])
    result_str = "орел" if is_heads else "решка"
    is_win = (choice == result_str)

    if is_win:
        win_amount = bet * 2
        if item == 7: win_amount = int(win_amount * 1.5) # Кольцо жадности
        add_balance(message.from_user.id, win_amount)
        txt = f"🪙 Выпал <b>{result_str}</b>!\n✅ Выиграл: <b>{win_amount}</b>"
        if item == 7: txt += " <i>(Кольцо жадности x1.5!)</i>"
        await message.answer(txt, parse_mode="HTML")
    else:
        if item == 1 or item == 8:
            add_balance(message.from_user.id, bet)
            await message.answer(f"🪙 Выпал <b>{result_str}</b>.\n🛡 Двуликая Монета/Щит вернули ставку!", parse_mode="HTML")
        else:
            await message.answer(f"🪙 Выпал <b>{result_str}</b>.\n❌ Проиграл <b>{bet}</b>.", parse_mode="HTML")

@dp.message(Command("кубик", "dice"))
async def play_dice(message: types.Message, command: CommandObject):
    ok, bet, err, item = process_bet(message.from_user.id, command.args)
    if not ok: return await message.answer(err)

    msg = await message.answer_dice(emoji="🎲")
    await asyncio.sleep(3.5)
    
    val = msg.dice.value
    if val >= 5:
        win_amount = bet * 2
        if item == 7: win_amount = int(win_amount * 1.5)
        add_balance(message.from_user.id, win_amount)
        txt = f"🎲 <b>{val}</b>! Выиграл: <b>{win_amount}</b>"
        await message.answer(txt, parse_mode="HTML")
    else:
        if item == 8:
            add_balance(message.from_user.id, bet)
            await message.answer(f"🎲 <b>{val}</b>. 🛡 Щит неудачника вернул ставку!", parse_mode="HTML")
        elif item == 2:
            add_balance(message.from_user.id, bet // 2)
            await message.answer(f"🎲 <b>{val}</b>. 🎲 Святые кости вернули половину ставки!", parse_mode="HTML")
        else:
            await message.answer(f"🎲 <b>{val}</b>.\n❌ Проиграл <b>{bet}</b>.", parse_mode="HTML")

@dp.message(Command("казино", "slots"))
async def play_slots(message: types.Message, command: CommandObject):
    ok, bet, err, item = process_bet(message.from_user.id, command.args)
    if not ok: return await message.answer(err)

    msg = await message.answer_dice(emoji="🎰")
    await asyncio.sleep(2.5)
    
    val = msg.dice.value
    is_win = False
    base_mult = 0
    
    if val == 64: is_win, base_mult = True, 10
    elif val in [1, 22, 43]: is_win, base_mult = True, 3

    if is_win:
        win_amount = bet * base_mult
        if item == 3: win_amount *= 2 # Секрет казино
        if item == 7: win_amount = int(win_amount * 1.5)
        
        add_balance(message.from_user.id, win_amount)
        txt = f"🎰 <b>Победа!</b> Выиграл: <b>{win_amount}</b>"
        if item == 3: txt += " <i>(Секрет казино x2!)</i>"
        await message.answer(txt, parse_mode="HTML")
    else:
        if item == 8:
            add_balance(message.from_user.id, bet)
            await message.answer(f"🎰 Не совпало. 🛡 Щит вернул ставку!", parse_mode="HTML")
        else:
            await message.answer(f"🎰 Не совпало.\n❌ Проиграл <b>{bet}</b>.", parse_mode="HTML")

@dp.message(Command("дартс", "darts"))
async def play_darts(message: types.Message, command: CommandObject):
    ok, bet, err, item = process_bet(message.from_user.id, command.args)
    if not ok: return await message.answer(err)

    msg = await message.answer_dice(emoji="🎯")
    await asyncio.sleep(3.0)
    
    val = msg.dice.value
    if val >= 5:
        win_amount = bet * (3 if val == 6 else 2)
        if item == 7: win_amount = int(win_amount * 1.5)
        add_balance(message.from_user.id, win_amount)
        await message.answer(f"🎯 Попал! Выиграл: <b>{win_amount}</b>", parse_mode="HTML")
    else:
        if item == 8:
            add_balance(message.from_user.id, bet)
            await message.answer("🎯 Промах. 🛡 Щит вернул ставку!", parse_mode="HTML")
        elif item == 4:
            add_balance(message.from_user.id, bet)
            await message.answer("🎯 Промах. 🎯 Острый дротик дал утешительный возврат!", parse_mode="HTML")
        else:
            await message.answer(f"🎯 Мимо.\n❌ Проиграл <b>{bet}</b>.", parse_mode="HTML")

@dp.message(Command("баскет", "баскетбол"))
async def play_basket(message: types.Message, command: CommandObject):
    ok, bet, err, item = process_bet(message.from_user.id, command.args)
    if not ok: return await message.answer(err)
    if item == 5: await message.answer("🏀 Применен Пружинистый мяч! Ставка не списана.")

    msg = await message.answer_dice(emoji="🏀")
    await asyncio.sleep(3.5)
    
    if msg.dice.value in [4, 5]:
        win_amount = bet * 2
        if item == 7: win_amount = int(win_amount * 1.5)
        add_balance(message.from_user.id, win_amount)
        await message.answer(f"🏀 ГОЛ! Выиграл: <b>{win_amount}</b>", parse_mode="HTML")
    else:
        if item == 8:
            add_balance(message.from_user.id, bet)
            await message.answer("🏀 Промах. 🛡 Щит вернул ставку!", parse_mode="HTML")
        else:
            await message.answer(f"🏀 Промах.\n❌ Проиграл <b>{bet}</b>.", parse_mode="HTML")

# --- ИГРА 6: Мины ---
active_mines = {}
mines_locks = {}
MINES_MULTIPLIERS = [1.0, 1.2, 1.5, 2.0, 2.8, 3.5]

@dp.message(Command("мины", "mines"))
async def play_mines(message: types.Message, command: CommandObject):
    user_id = message.from_user.id
    if user_id in active_mines: return await message.answer("⚠️ Заверши текущую игру!")

    ok, bet, err, item = process_bet(user_id, command.args)
    if not ok: return await message.answer(err)

    grid = ['M']*15 + ['B']*5 + ['S']*44
    random.shuffle(grid)

    active_mines[user_id] = {
        "bet": bet, "grid": grid, "revealed": [False]*64, "bags": 0, "item": item, "radar_used": False
    }
    await send_mines_board(message, user_id)

async def send_mines_board(message: types.Message, user_id: int, edit_message: types.Message = None):
    game = active_mines.get(user_id)
    if not game: return

    builder = InlineKeyboardBuilder()
    for i in range(64):
        if not game["revealed"][i]: builder.button(text="⬜", callback_data=f"m_{i}")
        else:
            c = game["grid"][i]
            if c == 'M': builder.button(text="💣", callback_data="ignore")
            elif c == 'B': builder.button(text="💰", callback_data="ignore")
            else: builder.button(text="🟫", callback_data="ignore")

    builder.adjust(8)
    
    current_mult = MINES_MULTIPLIERS[game["bags"]]
    if game["item"] == 7: current_mult *= 1.5
    take_amount = int(game["bet"] * current_mult)
    builder.row(types.InlineKeyboardButton(text=f"Забрать {take_amount} 💰", callback_data="m_take"))

    txt = f"💣 <b>Мины</b> | Ставка: {game['bet']}\n💰 Мешков: {game['bags']}/5"
    if game["item"] == 6 and not game["radar_used"]: txt += "\n📡 <i>Радар сапера АКТИВЕН</i>"
    
    if edit_message: await edit_message.edit_text(txt, reply_markup=builder.as_markup(), parse_mode="HTML")
    else: await message.answer(txt, reply_markup=builder.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data.startswith("m_"))
async def mines_callback(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in mines_locks: mines_locks[user_id] = asyncio.Lock()
        
    async with mines_locks[user_id]:
        if user_id not in active_mines: return await callback.answer("Игра устарела!", show_alert=True)
            
        game = active_mines[user_id]
        action = callback.data.split("_")[1]

        if action == "take":
            mult = MINES_MULTIPLIERS[game["bags"]]
            if game["item"] == 7: mult *= 1.5
            win_amount = int(game["bet"] * mult)
            add_balance(user_id, win_amount)
            del active_mines[user_id]
            await callback.message.edit_text(f"✅ Забрал <b>{win_amount}</b>!", parse_mode="HTML")
            return await callback.answer()

        if action.isdigit():
            idx = int(action)
            if game["revealed"][idx]: return await callback.answer("Уже открыто!")
            game["revealed"][idx] = True
            c = game["grid"][idx]

            if c == 'M': 
                if game["item"] == 6 and not game["radar_used"]:
                    game["radar_used"] = True
                    await send_mines_board(None, user_id, edit_message=callback.message)
                    return await callback.answer("Радар спас от первой мины!", show_alert=True)
                
                if game["item"] == 8:
                    add_balance(user_id, game["bet"])
                    del active_mines[user_id]
                    await callback.message.edit_text("💥 БУМ! Но 🛡 Щит вернул ставку!")
                    return await callback.answer("Щит спас!")
                    
                del active_mines[user_id]
                await callback.message.edit_text(f"💥 БУМ! Мина!\n❌ Проиграл <b>{game['bet']}</b>.", parse_mode="HTML")
                return await callback.answer("Ты взорвался!")
                
            elif c == 'B':
                game["bags"] += 1
                if game["bags"] >= 5:
                    mult = MINES_MULTIPLIERS[5]
                    if game["item"] == 7: mult *= 1.5
                    win_amount = int(game["bet"] * mult)
                    add_balance(user_id, win_amount)
                    del active_mines[user_id]
                    await callback.message.edit_text(f"🎉 ПОБЕДА! Все мешки найдены!\nВыиграл <b>{win_amount}</b>", parse_mode="HTML")
                    return await callback.answer("ДЖЕКПОТ!")
                else:
                    await send_mines_board(None, user_id, edit_message=callback.message)
                    return await callback.answer("Мешок!")
            else:
                await send_mines_board(None, user_id, edit_message=callback.message)
                return await callback.answer("Песок")

@dp.callback_query(F.data == "ignore")
async def ignore_callback(callback: types.CallbackQuery):
    await callback.answer()

async def main():
    init_db()
    await bot.delete_webhook(drop_pending_updates=True) 
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
