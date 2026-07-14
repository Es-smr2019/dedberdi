import asyncio
import logging
import os
import time
import random
import aiosqlite
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, CommandObject

# Получаем токен из Environment Variables на Bothost
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    TOKEN = "ТВОЙ_ТОКЕН_ЗДЕСЬ"  # Для локального запуска

bot = Bot(token=TOKEN)
dp = Dispatcher()
logging.basicConfig(level=logging.INFO)

DB_NAME = "bot_database.db"
COOLDOWN_SECONDS = 5.0 # Кулдаун 5 секунд

# --- Вспомогательные функции для базы данных ---
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS users
                            (user_id INTEGER PRIMARY KEY, balance INTEGER, last_play REAL)''')
        await db.commit()

async def get_user(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT balance, last_play FROM users WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone()

async def update_balance_and_time(user_id, amount_change):
    current_time = time.time()
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET balance = balance + ?, last_play = ? WHERE user_id = ?", 
                       (amount_change, current_time, user_id))
        await db.commit()

async def register_user(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id, balance, last_play) VALUES (?, ?, ?)", 
                       (user_id, 1000, 0))
        await db.commit()

async def check_preconditions(user_id, bet_str):
    """
    Проверяет: зарегистрирован ли игрок, прошел ли кулдаун, правильная ли ставка и хватает ли денег.
    """
    user = await get_user(user_id)
    if not user:
        return False, 0, "❌ Ты не зарегистрирован! Напиши /start"
        
    balance, last_play = user
    
    # 1. Проверка кулдауна
    elapsed = time.time() - last_play
    if elapsed < COOLDOWN_SECONDS:
        return False, 0, f"⏳ Кулдаун! Подожди еще {int(COOLDOWN_SECONDS - elapsed) + 1} сек. перед игрой!"

    # 2. Проверка ставки
    if not bet_str or not bet_str.isdigit():
        return False, 0, "⚠️ Ставка должна быть целым числом! Пример: 100"
        
    bet = int(bet_str)
    if bet <= 0:
        return False, 0, "⚠️ Ставка должна быть больше нуля!"
        
    # 3. Проверка баланса
    if balance < bet:
        return False, 0, f"❌ Недостаточно монет! Твой баланс: {balance} 💰"
        
    return True, bet, ""


# --- Команды ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await register_user(message.from_user.id)
    await message.answer(
        "🎉 Добро пожаловать!\n"
        "Тебе начислены стартовые <b>1000 монет</b> 💰.\n\n"
        "🎮 <b>Доступные игры:</b>\n"
        "1. <code>/flip &lt;ставка&gt; &lt;орел/решка&gt;</code> - Монетка (х2)\n"
        "2. <code>/dice &lt;ставка&gt;</code> - Кубик 🎲 (выигрыш на 5 и 6 - х2)\n"
        "3. <code>/slots &lt;ставка&gt;</code> - Казино 🎰 (3 в ряд - х3, 777 - х10!)\n\n"
        "💳 Баланс: <code>/b</code>\n"
        "<i>У игр есть кулдаун 5 секунд для защиты от спама!</i>",
        parse_mode="HTML"
    )

@dp.message(Command("b", "balance"))
async def cmd_balance(message: types.Message):
    user = await get_user(message.from_user.id)
    if user:
        await message.answer(f"💰 Твой баланс: <b>{user[0]}</b> монет.", parse_mode="HTML")
    else:
        await message.answer("❌ Ты не зарегистрирован! Напиши /start")

# --- ИГРА 1: Орел и Решка ---
@dp.message(Command("flip"))
async def play_flip(message: types.Message, command: CommandObject):
    if not command.args:
        return await message.answer("⚠️ Формат: /flip <ставка> <орел/решка>\nПример: /flip 100 орел")
    
    parts = command.args.split()
    if len(parts) != 2:
        return await message.answer("⚠️ Формат: /flip <ставка> <орел/решка>")
        
    bet_str, choice = parts[0], parts[1].lower()
    if choice not in ["орел", "решка"]:
        return await message.answer("⚠️ Выбери 'орел' или 'решка'!")

    ok, bet, err = await check_preconditions(message.from_user.id, bet_str)
    if not ok:
        return await message.answer(err)

    await update_balance_and_time(message.from_user.id, 0) # Обновляем время кулдауна
    
    is_heads = random.choice([True, False])
    result_str = "орел" if is_heads else "решка"
    
    if choice == result_str:
        await update_balance_and_time(message.from_user.id, bet)
        await message.answer(f"🪙 Выпал <b>{result_str}</b>!\n✅ Ты выиграл <b>{bet}</b> монет!", parse_mode="HTML")
    else:
        await update_balance_and_time(message.from_user.id, -bet)
        await message.answer(f"🪙 Выпал <b>{result_str}</b>.\n❌ Ты проиграл <b>{bet}</b> монет.", parse_mode="HTML")

# --- ИГРА 2: Кубик (Dice) ---
@dp.message(Command("dice"))
async def play_dice(message: types.Message, command: CommandObject):
    ok, bet, err = await check_preconditions(message.from_user.id, command.args)
    if not ok:
        return await message.answer(err)

    await update_balance_and_time(message.from_user.id, 0) 

    msg = await message.answer_dice(emoji="🎲")
    await asyncio.sleep(3.5) # Ждем анимацию
    
    val = msg.dice.value
    if val >= 5: # Выигрыш если выпало 5 или 6
        win_amount = bet * 2
        await update_balance_and_time(message.from_user.id, win_amount)
        await message.answer(f"🎲 Выпало <b>{val}</b>!\n✅ Отличный бросок! Ты выиграл <b>{win_amount}</b> монет!", parse_mode="HTML")
    else:
        await update_balance_and_time(message.from_user.id, -bet)
        await message.answer(f"🎲 Выпало <b>{val}</b>.\n❌ Увы, ты проиграл <b>{bet}</b> монет.", parse_mode="HTML")

# --- ИГРА 3: Слоты (Казино) ---
@dp.message(Command("slots"))
async def play_slots(message: types.Message, command: CommandObject):
    ok, bet, err = await check_preconditions(message.from_user.id, command.args)
    if not ok:
        return await message.answer(err)

    await update_balance_and_time(message.from_user.id, 0)

    msg = await message.answer_dice(emoji="🎰")
    await asyncio.sleep(2.5) # Ждем анимацию
    
    val = msg.dice.value
    if val == 64:
        win_amount = bet * 10
        await update_balance_and_time(message.from_user.id, win_amount)
        await message.answer(f"🎰 <b>ДЖЕКПОТ (777)!</b>\n🔥 Невероятно! Ты выиграл <b>{win_amount}</b> монет!", parse_mode="HTML")
    elif val in [1, 22, 43]:
        win_amount = bet * 3
        await update_balance_and_time(message.from_user.id, win_amount)
        await message.answer(f"🎰 Три в ряд!\n✅ Ты выиграл <b>{win_amount}</b> монет!", parse_mode="HTML")
    else:
        await update_balance_and_time(message.from_user.id, -bet)
        await message.answer(f"🎰 Комбинация не совпала.\n❌ Ты проиграл <b>{bet}</b> монет.", parse_mode="HTML")

async def main():
    print("Бот запускается...")
    await init_db()
    await bot.delete_webhook(drop_pending_updates=True) 
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())