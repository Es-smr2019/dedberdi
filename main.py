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

# Получаем токен из Environment Variables на Bothost
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    TOKEN = "8987715811:AAHhMtYxhuKV3F5XtwPwm2PNzyfnW1RuZ1w"

bot = Bot(token=TOKEN)
dp = Dispatcher()
logging.basicConfig(level=logging.INFO)

DB_NAME = "bot_database.db"
COOLDOWN_SECONDS = 5.0

# Глобальная блокировка для базы данных (исправляет дюпы и ошибки database is locked)
db_lock = threading.Lock()

# --- Вспомогательные функции БД ---
def init_db():
    with db_lock:
        with sqlite3.connect(DB_NAME) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS users
                          (user_id INTEGER PRIMARY KEY, balance INTEGER, last_play REAL)''')
            db.commit()

def get_user(user_id):
    with db_lock:
        with sqlite3.connect(DB_NAME) as db:
            cursor = db.cursor()
            cursor.execute("SELECT balance, last_play FROM users WHERE user_id = ?", (user_id,))
            return cursor.fetchone()

def register_user(user_id):
    with db_lock:
        with sqlite3.connect(DB_NAME) as db:
            db.execute("INSERT OR IGNORE INTO users (user_id, balance, last_play) VALUES (?, ?, ?)", 
                       (user_id, 1000, 0))
            db.commit()

def add_balance(user_id, amount):
    """Просто добавляет монеты (выигрыш)"""
    with db_lock:
        with sqlite3.connect(DB_NAME) as db:
            db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
            db.commit()

def process_bet(user_id, bet_str):
    """
    АНТИ-ДЮП ФУНКЦИЯ: Проверяет баланс и СРАЗУ списывает ставку внутри блокировки.
    Если игрок спамит, баланс спишется последовательно, и он не сможет уйти в минус.
    """
    if not bet_str or not bet_str.isdigit():
        return False, 0, "⚠️ Ставка должна быть целым числом! Пример: 100"
        
    bet = int(bet_str)
    if bet <= 0:
        return False, 0, "⚠️ Ставка должна быть больше нуля!"

    with db_lock:
        with sqlite3.connect(DB_NAME) as db:
            cursor = db.cursor()
            cursor.execute("SELECT balance, last_play FROM users WHERE user_id = ?", (user_id,))
            user = cursor.fetchone()
            
            if not user:
                return False, 0, "❌ Ты не зарегистрирован! Напиши /старт"
                
            balance, last_play = user
            
            elapsed = time.time() - last_play
            if elapsed < COOLDOWN_SECONDS:
                return False, 0, f"⏳ Кулдаун! Подожди еще {int(COOLDOWN_SECONDS - elapsed) + 1} сек."
                
            if balance < bet:
                return False, 0, f"❌ Недостаточно монет! Твой баланс: <b>{balance}</b> 💰"
            
            # Атомарное списание ставки и обновление времени
            current_time = time.time()
            db.execute("UPDATE users SET balance = balance - ?, last_play = ? WHERE user_id = ?", 
                       (bet, current_time, user_id))
            db.commit()
            return True, bet, ""

def transfer_money_atomic(from_user, to_user, amount):
    """Атомарный перевод валюты (без дюпов)"""
    if from_user == to_user:
        return False, "⚠️ Нельзя переводить самому себе!"
    if amount <= 0:
        return False, "⚠️ Сумма перевода должна быть больше нуля!"
        
    with db_lock:
        with sqlite3.connect(DB_NAME) as db:
            cursor = db.cursor()
            cursor.execute("SELECT balance FROM users WHERE user_id = ?", (from_user,))
            sender = cursor.fetchone()
            
            if not sender or sender[0] < amount:
                return False, "❌ Недостаточно средств."
                
            db.execute("INSERT OR IGNORE INTO users (user_id, balance, last_play) VALUES (?, ?, ?)", 
                       (to_user, 1000, 0))
            db.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, from_user))
            db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, to_user))
            db.commit()
            return True, f"✅ Успешно переведено <b>{amount}</b> 💰!"

# --- Глобальное хранилище ---
active_mines = {}
mines_locks = {} # Блокировки для кнопок, чтобы избежать дабл-кликов
MINES_MULTIPLIERS = [1.0, 1.2, 1.5, 2.0, 2.8, 3.5]

# --- КОМАНДЫ И ПЕРЕВОДЫ ---
@dp.message(Command("start", "старт"))
async def cmd_start(message: types.Message):
    register_user(message.from_user.id)
    await message.answer(
        "🎉 Добро пожаловать!\n"
        "Тебе начислены стартовые <b>1000 монет</b> 💰.\n\n"
        "🎮 <b>Игры:</b>\n"
        "1. <code>/монета &lt;ставка&gt; &lt;орел/решка&gt;</code> - Орел или Решка\n"
        "2. <code>/кубик &lt;ставка&gt;</code> - Кости 🎲 (5 или 6 = х2)\n"
        "3. <code>/казино &lt;ставка&gt;</code> - Слоты 🎰 (до х10)\n"
        "4. <code>/дартс &lt;ставка&gt;</code> - Дартс 🎯 (в яблочко = х3)\n"
        "5. <code>/баскет &lt;ставка&gt;</code> - Баскетбол 🏀 (попал = х2)\n"
        "6. <code>/мины &lt;ставка&gt;</code> - Поле 8х8. Ищи мешки 💰\n\n"
        "💸 <b>Перевод игроку:</b>\n"
        "Просто <b>ответь на сообщение</b> нужного человека текстом <code>+500</code> (или любая сумма).",
        parse_mode="HTML"
    )

@dp.message(Command("баланс", "balance"))
async def cmd_balance(message: types.Message):
    user = get_user(message.from_user.id)
    if user:
        await message.answer(f"💰 Твой баланс: <b>{user[0]}</b> монет.", parse_mode="HTML")
    else:
        await message.answer("❌ Ты не зарегистрирован! Напиши /старт")

# --- ГЕНИАЛЬНЫЙ И ПРОСТОЙ ПЕРЕВОД (НА ОТВЕТ +500) ---
@dp.message(F.reply_to_message & F.text)
async def quick_transfer(message: types.Message):
    text = message.text.strip()
    # Проверяем, что сообщение начинается на '+' и дальше идут только цифры
    if text.startswith("+") and text[1:].isdigit():
        amount = int(text[1:])
        target_user = message.reply_to_message.from_user
        
        if target_user.is_bot:
            return await message.answer("⚠️ Ботам нельзя переводить деньги!")
            
        ok, text_response = transfer_money_atomic(message.from_user.id, target_user.id, amount)
        await message.answer(text_response, parse_mode="HTML")


# --- ИГРА 1: Монетка ---
@dp.message(Command("монета", "flip"))
async def play_flip(message: types.Message, command: CommandObject):
    if not command.args: return await message.answer("⚠️ Формат: /монета <ставка> <орел/решка>")
    
    parts = command.args.split()
    if len(parts) != 2: return await message.answer("⚠️ Формат: /монета <ставка> <орел/решка>")
        
    choice = parts[1].lower()
    if choice not in ["орел", "решка"]: return await message.answer("⚠️ Выбери 'орел' или 'решка'!")

    # Списываем ставку заранее
    ok, bet, err = process_bet(message.from_user.id, parts[0])
    if not ok: return await message.answer(err)

    is_heads = random.choice([True, False])
    result_str = "орел" if is_heads else "решка"
    
    if choice == result_str:
        win_amount = bet * 2
        add_balance(message.from_user.id, win_amount) # Выдаем выигрыш
        await message.answer(f"🪙 Выпал <b>{result_str}</b>!\n✅ Ты выиграл <b>{win_amount}</b> монет!", parse_mode="HTML")
    else:
        await message.answer(f"🪙 Выпал <b>{result_str}</b>.\n❌ Ты проиграл <b>{bet}</b> монет.", parse_mode="HTML")

# --- ИГРА 2: Кубик ---
@dp.message(Command("кубик", "dice"))
async def play_dice(message: types.Message, command: CommandObject):
    ok, bet, err = process_bet(message.from_user.id, command.args)
    if not ok: return await message.answer(err)

    msg = await message.answer_dice(emoji="🎲")
    await asyncio.sleep(3.5)
    
    val = msg.dice.value
    if val >= 5:
        win_amount = bet * 2
        add_balance(message.from_user.id, win_amount)
        await message.answer(f"🎲 Выпало <b>{val}</b>!\n✅ Отличный бросок! Выигрыш: <b>{win_amount}</b> монет!", parse_mode="HTML")
    else:
        await message.answer(f"🎲 Выпало <b>{val}</b>.\n❌ Ты проиграл <b>{bet}</b> монет.", parse_mode="HTML")

# --- ИГРА 3: Казино ---
@dp.message(Command("казино", "slots"))
async def play_slots(message: types.Message, command: CommandObject):
    ok, bet, err = process_bet(message.from_user.id, command.args)
    if not ok: return await message.answer(err)

    msg = await message.answer_dice(emoji="🎰")
    await asyncio.sleep(2.5)
    
    val = msg.dice.value
    if val == 64:
        win_amount = bet * 10
        add_balance(message.from_user.id, win_amount)
        await message.answer(f"🎰 <b>ДЖЕКПОТ (777)!</b>\n🔥 Ты выиграл <b>{win_amount}</b> монет!", parse_mode="HTML")
    elif val in [1, 22, 43]:
        win_amount = bet * 3
        add_balance(message.from_user.id, win_amount)
        await message.answer(f"🎰 Три в ряд!\n✅ Ты выиграл <b>{win_amount}</b> монет!", parse_mode="HTML")
    else:
        await message.answer(f"🎰 Комбинация не совпала.\n❌ Ты проиграл <b>{bet}</b> монет.", parse_mode="HTML")

# --- ИГРА 4: Дартс (НОВАЯ) ---
@dp.message(Command("дартс", "darts"))
async def play_darts(message: types.Message, command: CommandObject):
    ok, bet, err = process_bet(message.from_user.id, command.args)
    if not ok: return await message.answer(err)

    msg = await message.answer_dice(emoji="🎯")
    await asyncio.sleep(3.0)
    
    val = msg.dice.value
    if val == 6: # Прямо в центр
        win_amount = bet * 3
        add_balance(message.from_user.id, win_amount)
        await message.answer(f"🎯 <b>В ЯБЛОЧКО!</b>\n🔥 Идеально! Ты выиграл <b>{win_amount}</b> монет!", parse_mode="HTML")
    elif val == 5: # Очень близко
        win_amount = int(bet * 1.5)
        add_balance(message.from_user.id, win_amount)
        await message.answer(f"🎯 Рядом с центром!\n✅ Ты выиграл <b>{win_amount}</b> монет!", parse_mode="HTML")
    else:
        await message.answer(f"🎯 Мимо центра.\n❌ Ты проиграл <b>{bet}</b> монет.", parse_mode="HTML")

# --- ИГРА 5: Баскетбол (НОВАЯ) ---
@dp.message(Command("баскет", "баскетбол"))
async def play_basket(message: types.Message, command: CommandObject):
    ok, bet, err = process_bet(message.from_user.id, command.args)
    if not ok: return await message.answer(err)

    msg = await message.answer_dice(emoji="🏀")
    await asyncio.sleep(3.5)
    
    val = msg.dice.value
    # В телеграме значения 4 и 5 - это попадание в корзину
    if val in [4, 5]:
        win_amount = bet * 2
        add_balance(message.from_user.id, win_amount)
        await message.answer(f"🏀 <b>ГОЛ!</b>\n✅ Мяч в корзине! Ты выиграл <b>{win_amount}</b> монет!", parse_mode="HTML")
    else:
        await message.answer(f"🏀 Промах.\n❌ Мяч отскочил. Ты проиграл <b>{bet}</b> монет.", parse_mode="HTML")

# --- ИГРА 6: Мины ---
@dp.message(Command("мины", "mines"))
async def play_mines(message: types.Message, command: CommandObject):
    user_id = message.from_user.id
    
    if user_id in active_mines:
        return await message.answer("⚠️ У тебя уже есть активная игра в мины! Заверши её сначала.")

    ok, bet, err = process_bet(user_id, command.args)
    if not ok: return await message.answer(err)

    grid = ['M'] * 15 + ['B'] * 5 + ['S'] * 44
    random.shuffle(grid)

    active_mines[user_id] = {
        "bet": bet,
        "grid": grid,
        "revealed": [False] * 64,
        "bags_found": 0
    }

    await send_mines_board(message, user_id)

async def send_mines_board(message: types.Message, user_id: int, edit_message: types.Message = None):
    game = active_mines.get(user_id)
    if not game: return

    builder = InlineKeyboardBuilder()
    for i in range(64):
        if not game["revealed"][i]:
            builder.button(text="⬜", callback_data=f"m_{i}")
        else:
            cell = game["grid"][i]
            if cell == 'M': builder.button(text="💣", callback_data="ignore")
            elif cell == 'B': builder.button(text="💰", callback_data="ignore")
            else: builder.button(text="🟫", callback_data="ignore")

    builder.adjust(8)
    
    current_mult = MINES_MULTIPLIERS[game["bags_found"]]
    take_amount = int(game["bet"] * current_mult)
    builder.row(types.InlineKeyboardButton(text=f"Забрать {take_amount} 💰", callback_data="m_take"))

    text = f"💣 <b>Минное поле 8x8</b>\n💸 Ставка: <b>{game['bet']}</b>\n💰 Найдено мешков: <b>{game['bags_found']}/5</b>\n📈 Множитель: <b>x{current_mult}</b>"

    if edit_message:
        await edit_message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    else:
        await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data.startswith("m_"))
async def mines_callback(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    # Защита от дюпов: Асинхронный лок для конкретного игрока
    if user_id not in mines_locks:
        mines_locks[user_id] = asyncio.Lock()
        
    async with mines_locks[user_id]:
        if user_id not in active_mines:
            return await callback.answer("Эта игра завершена!", show_alert=True)
            
        game = active_mines[user_id]
        action = callback.data.split("_")[1]

        if action == "take":
            win_amount = int(game["bet"] * MINES_MULTIPLIERS[game["bags_found"]])
            add_balance(user_id, win_amount) # Зачисляет выигрыш
            del active_mines[user_id]
            
            builder = InlineKeyboardBuilder()
            for i in range(64):
                if game["grid"][i] == 'M': builder.button(text="💣", callback_data="ignore")
                elif game["grid"][i] == 'B': builder.button(text="💰", callback_data="ignore")
                else: builder.button(text="🟫", callback_data="ignore")
            builder.adjust(8)
            
            await callback.message.edit_text(
                f"✅ Ты забрал выигрыш!\n💰 Выиграно: <b>{win_amount}</b> монет", 
                reply_markup=builder.as_markup(), parse_mode="HTML"
            )
            return await callback.answer()

        if action.isdigit():
            idx = int(action)
            if game["revealed"][idx]:
                return await callback.answer("Уже открыто!")
                
            game["revealed"][idx] = True
            cell = game["grid"][idx]

            if cell == 'M': 
                del active_mines[user_id]
                builder = InlineKeyboardBuilder()
                for i in range(64):
                    if game["grid"][i] == 'M': builder.button(text="💣", callback_data="ignore")
                    elif game["grid"][i] == 'B': builder.button(text="💰", callback_data="ignore")
                    else: builder.button(text="🟫", callback_data="ignore")
                builder.adjust(8)
                
                await callback.message.edit_text(
                    f"💥 <b>БУМ!</b> Ты нарвался на мину!\n❌ Ставка <b>{game['bet']}</b> сгорела.", 
                    reply_markup=builder.as_markup(), parse_mode="HTML"
                )
                return await callback.answer("Ты взорвался!")
                
            elif cell == 'B':
                game["bags_found"] += 1
                if game["bags_found"] >= 5:
                    win_amount = int(game["bet"] * MINES_MULTIPLIERS[5])
                    add_balance(user_id, win_amount)
                    del active_mines[user_id]
                    
                    builder = InlineKeyboardBuilder()
                    for i in range(64):
                        if game["grid"][i] == 'M': builder.button(text="💣", callback_data="ignore")
                        elif game["grid"][i] == 'B': builder.button(text="💰", callback_data="ignore")
                        else: builder.button(text="🟫", callback_data="ignore")
                    builder.adjust(8)
                    
                    await callback.message.edit_text(
                        f"🎉 <b>ПОБЕДА!</b> Ты нашел все мешки!\n💰 Выиграно: <b>{win_amount}</b> монет (Множитель x3.5)", 
                        reply_markup=builder.as_markup(), parse_mode="HTML"
                    )
                    return await callback.answer("ДЖЕКПОТ!")
                else:
                    await send_mines_board(None, user_id, edit_message=callback.message)
                    return await callback.answer("Нашел мешок! Множитель повышен!")
                    
            elif cell == 'S':
                await send_mines_board(None, user_id, edit_message=callback.message)
                return await callback.answer("Фух, тут песок! Копаем дальше.")

@dp.callback_query(F.data == "ignore")
async def ignore_callback(callback: types.CallbackQuery):
    await callback.answer()

async def main():
    print("Бот запускается...")
    init_db()
    await bot.delete_webhook(drop_pending_updates=True) 
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
