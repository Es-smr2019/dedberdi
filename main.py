import asyncio
import logging
import os
import time
import random
import sqlite3
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Получаем токен из Environment Variables на Bothost
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    TOKEN = "8987715811:AAHhMtYxhuKV3F5XtwPwm2PNzyfnW1RuZ1w"  # Для локального запуска

bot = Bot(token=TOKEN)
dp = Dispatcher()
logging.basicConfig(level=logging.INFO)

DB_NAME = "bot_database.db"
COOLDOWN_SECONDS = 5.0 # Кулдаун 5 секунд

# --- Вспомогательные функции для базы данных ---
def init_db():
    with sqlite3.connect(DB_NAME) as db:
        db.execute('''CREATE TABLE IF NOT EXISTS users
                      (user_id INTEGER PRIMARY KEY, balance INTEGER, last_play REAL)''')
        db.commit()

def get_user(user_id):
    with sqlite3.connect(DB_NAME) as db:
        cursor = db.cursor()
        cursor.execute("SELECT balance, last_play FROM users WHERE user_id = ?", (user_id,))
        return cursor.fetchone()

def update_balance_and_time(user_id, amount_change, update_time=True):
    with sqlite3.connect(DB_NAME) as db:
        if update_time:
            current_time = time.time()
            db.execute("UPDATE users SET balance = balance + ?, last_play = ? WHERE user_id = ?", 
                       (amount_change, current_time, user_id))
        else:
            db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", 
                       (amount_change, user_id))
        db.commit()

def register_user(user_id):
    with sqlite3.connect(DB_NAME) as db:
        db.execute("INSERT OR IGNORE INTO users (user_id, balance, last_play) VALUES (?, ?, ?)", 
                   (user_id, 1000, 0))
        db.commit()

def transfer_money(from_user, to_user, amount):
    with sqlite3.connect(DB_NAME) as db:
        cursor = db.cursor()
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (from_user,))
        sender = cursor.fetchone()
        
        if not sender or sender[0] < amount:
            return False, "❌ Недостаточно средств."
            
        # Убедимся, что получатель есть в базе
        db.execute("INSERT OR IGNORE INTO users (user_id, balance, last_play) VALUES (?, ?, ?)", 
                   (to_user, 1000, 0))
                   
        db.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, from_user))
        db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, to_user))
        db.commit()
        return True, "✅ Успешный перевод!"

def check_preconditions(user_id, bet_str):
    user = get_user(user_id)
    if not user:
        return False, 0, "❌ Ты не зарегистрирован! Напиши /старт"
        
    balance, last_play = user
    
    elapsed = time.time() - last_play
    if elapsed < COOLDOWN_SECONDS:
        return False, 0, f"⏳ Подожди еще {int(COOLDOWN_SECONDS - elapsed) + 1} сек.!"

    if not bet_str or not bet_str.isdigit():
        return False, 0, "⚠️ Ставка должна быть целым числом! Пример: 100"
        
    bet = int(bet_str)
    if bet <= 0:
        return False, 0, "⚠️ Ставка должна быть больше нуля!"
        
    if balance < bet:
        return False, 0, f"❌ Недостаточно монет! Твой баланс: {balance} 💰"
        
    return True, bet, ""

# --- Глобальное хранилище для игр "Мины" ---
active_mines = {}
MINES_MULTIPLIERS = [1.0, 1.2, 1.5, 2.0, 2.8, 3.5] # Множители за мешки

# --- Команды ---
@dp.message(Command("start", "старт"))
async def cmd_start(message: types.Message):
    register_user(message.from_user.id)
    await message.answer(
        "🎉 Добро пожаловать!\n"
        "Тебе начислены стартовые <b>1000 монет</b> 💰.\n\n"
        "🎮 <b>Игры:</b>\n"
        "1. <code>/монета &lt;ставка&gt; &lt;орел/решка&gt;</code> - Орел или Решка\n"
        "2. <code>/кубик &lt;ставка&gt;</code> - Кубик 🎲 (выигрыш на 5 и 6)\n"
        "3. <code>/казино &lt;ставка&gt;</code> - Слоты 🎰 (3 в ряд - х3, 777 - х10)\n"
        "4. <code>/мины &lt;ставка&gt;</code> - Поле 8х8. Ищи мешки с деньгами и обходи бомбы! 💣\n\n"
        "💸 <b>Экономика:</b>\n"
        "• <code>/баланс</code> - Узнать счет\n"
        "• <code>/перевод &lt;сумма&gt;</code> (ответь на сообщение игрока)\n"
        "• <code>/перевод &lt;сумма&gt; &lt;ID_игрока&gt;</code>\n\n"
        "<i>У игр есть защита от спама - 5 секунд.</i>",
        parse_mode="HTML"
    )

@dp.message(Command("баланс", "balance"))
async def cmd_balance(message: types.Message):
    user = get_user(message.from_user.id)
    if user:
        await message.answer(f"💰 Твой баланс: <b>{user[0]}</b> монет.", parse_mode="HTML")
    else:
        await message.answer("❌ Ты не зарегистрирован! Напиши /старт")

@dp.message(Command("перевод", "pay"))
async def cmd_transfer(message: types.Message, command: CommandObject):
    user_id = message.from_user.id
    args = command.args
    
    if not args:
        return await message.answer("⚠️ Формат: /перевод <сумма> <ID> (или реплай на сообщение)")

    parts = args.split()
    amount_str = parts[0]
    
    if not amount_str.isdigit() or int(amount_str) <= 0:
        return await message.answer("⚠️ Сумма перевода должна быть целым числом больше нуля!")
    amount = int(amount_str)

    target_id = None
    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
    elif len(parts) > 1 and parts[1].isdigit():
        target_id = int(parts[1])
        
    if not target_id:
        return await message.answer("⚠️ Укажи ID получателя или ответь на его сообщение командой!")
        
    if target_id == user_id:
        return await message.answer("⚠️ Нельзя переводить монеты самому себе!")

    success, text = transfer_money(user_id, target_id, amount)
    await message.answer(text)

# --- ИГРА 1: Монетка ---
@dp.message(Command("монета", "flip"))
async def play_flip(message: types.Message, command: CommandObject):
    if not command.args:
        return await message.answer("⚠️ Формат: /монета <ставка> <орел/решка>")
    
    parts = command.args.split()
    if len(parts) != 2:
        return await message.answer("⚠️ Формат: /монета <ставка> <орел/решка>")
        
    bet_str, choice = parts[0], parts[1].lower()
    if choice not in ["орел", "решка"]:
        return await message.answer("⚠️ Выбери 'орел' или 'решка'!")

    ok, bet, err = check_preconditions(message.from_user.id, bet_str)
    if not ok: return await message.answer(err)

    update_balance_and_time(message.from_user.id, 0)
    is_heads = random.choice([True, False])
    result_str = "орел" if is_heads else "решка"
    
    if choice == result_str:
        update_balance_and_time(message.from_user.id, bet)
        await message.answer(f"🪙 Выпал <b>{result_str}</b>!\n✅ Ты выиграл <b>{bet}</b> монет!", parse_mode="HTML")
    else:
        update_balance_and_time(message.from_user.id, -bet)
        await message.answer(f"🪙 Выпал <b>{result_str}</b>.\n❌ Ты проиграл <b>{bet}</b> монет.", parse_mode="HTML")

# --- ИГРА 2: Кубик ---
@dp.message(Command("кубик", "dice"))
async def play_dice(message: types.Message, command: CommandObject):
    ok, bet, err = check_preconditions(message.from_user.id, command.args)
    if not ok: return await message.answer(err)

    update_balance_and_time(message.from_user.id, 0) 
    msg = await message.answer_dice(emoji="🎲")
    await asyncio.sleep(3.5)
    
    val = msg.dice.value
    if val >= 5:
        win_amount = bet * 2
        update_balance_and_time(message.from_user.id, win_amount)
        await message.answer(f"🎲 Выпало <b>{val}</b>!\n✅ Отличный бросок! Ты выиграл <b>{win_amount}</b> монет!", parse_mode="HTML")
    else:
        update_balance_and_time(message.from_user.id, -bet)
        await message.answer(f"🎲 Выпало <b>{val}</b>.\n❌ Ты проиграл <b>{bet}</b> монет.", parse_mode="HTML")

# --- ИГРА 3: Казино ---
@dp.message(Command("казино", "slots"))
async def play_slots(message: types.Message, command: CommandObject):
    ok, bet, err = check_preconditions(message.from_user.id, command.args)
    if not ok: return await message.answer(err)

    update_balance_and_time(message.from_user.id, 0)
    msg = await message.answer_dice(emoji="🎰")
    await asyncio.sleep(2.5)
    
    val = msg.dice.value
    if val == 64:
        win_amount = bet * 10
        update_balance_and_time(message.from_user.id, win_amount)
        await message.answer(f"🎰 <b>ДЖЕКПОТ (777)!</b>\n🔥 Ты выиграл <b>{win_amount}</b> монет!", parse_mode="HTML")
    elif val in [1, 22, 43]:
        win_amount = bet * 3
        update_balance_and_time(message.from_user.id, win_amount)
        await message.answer(f"🎰 Три в ряд!\n✅ Ты выиграл <b>{win_amount}</b> монет!", parse_mode="HTML")
    else:
        update_balance_and_time(message.from_user.id, -bet)
        await message.answer(f"🎰 Комбинация не совпала.\n❌ Ты проиграл <b>{bet}</b> монет.", parse_mode="HTML")

# --- ИГРА 4: Мины (Поле 8х8) ---
@dp.message(Command("мины", "mines"))
async def play_mines(message: types.Message, command: CommandObject):
    user_id = message.from_user.id
    ok, bet, err = check_preconditions(user_id, command.args)
    if not ok: return await message.answer(err)

    if user_id in active_mines:
        return await message.answer("⚠️ У тебя уже есть активная игра в мины! Заверши её сначала.")

    # Списываем ставку сразу
    update_balance_and_time(user_id, -bet)

    # Генерация поля 8х8 (64 клетки)
    # M = Мина (15 шт), B = Деньги (5 шт), S = Песок (44 шт)
    grid = ['M'] * 15 + ['B'] * 5 + ['S'] * 44
    random.shuffle(grid)

    active_mines[user_id] = {
        "bet": bet,
        "grid": grid,
        "revealed": [False] * 64,
        "bags_found": 0,
        "active": True
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

    builder.adjust(8) # 8 кнопок в ряд
    
    current_mult = MINES_MULTIPLIERS[game["bags_found"]]
    take_amount = int(game["bet"] * current_mult)
    builder.row(types.InlineKeyboardButton(text=f"Забрать {take_amount} 💰", callback_data="m_take"))

    text = f"💣 <b>Минное поле 8x8</b>\n💸 Ставка: <b>{game['bet']}</b>\n💰 Найдено мешков: <b>{game['bags_found']}/5</b>\n📈 Текущий множитель: <b>x{current_mult}</b>"

    if edit_message:
        await edit_message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    else:
        await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data.startswith("m_"))
async def mines_callback(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    if user_id not in active_mines:
        return await callback.answer("Эта игра устарела или не твоя!", show_alert=True)
        
    game = active_mines[user_id]
    action = callback.data.split("_")[1]

    if action == "take":
        win_amount = int(game["bet"] * MINES_MULTIPLIERS[game["bags_found"]])
        update_balance_and_time(user_id, win_amount, update_time=False)
        del active_mines[user_id]
        
        # Показываем все бомбы
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

        if cell == 'M': # Взрыв
            del active_mines[user_id]
            # Раскрываем все поле при проигрыше
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
            
        elif cell == 'B': # Мешок с деньгами
            game["bags_found"] += 1
            if game["bags_found"] >= 5: # Выиграл максимум
                win_amount = int(game["bet"] * MINES_MULTIPLIERS[5])
                update_balance_and_time(user_id, win_amount, update_time=False)
                del active_mines[user_id]
                
                builder = InlineKeyboardBuilder()
                for i in range(64):
                    if game["grid"][i] == 'M': builder.button(text="💣", callback_data="ignore")
                    elif game["grid"][i] == 'B': builder.button(text="💰", callback_data="ignore")
                    else: builder.button(text="🟫", callback_data="ignore")
                builder.adjust(8)
                
                await callback.message.edit_text(
                    f"🎉 <b>ПОБЕДА!</b> Ты нашел все мешки!\n💰 Выиграно: <b>{win_amount}</b> монет (Максимальный множитель x3.5)", 
                    reply_markup=builder.as_markup(), parse_mode="HTML"
                )
                return await callback.answer("ДЖЕКПОТ!")
            else:
                await send_mines_board(None, user_id, edit_message=callback.message)
                return await callback.answer("Нашел мешок! Множитель повышен!")
                
        elif cell == 'S': # Песок
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
