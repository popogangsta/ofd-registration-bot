import os
import asyncio
import logging
import sqlite3
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, FSInputFile

# ==== НАСТРОЙКИ ====
BOT_TOKEN = os.getenv("BOT_TOKEN")  # берётся из переменной окружения на хостинге
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))  # берётся из переменной окружения на хостинге

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# В памяти: id пользователей, которые сейчас "на связи" с админом
support_active = set()

# В памяти: связь "id сообщения у админа" -> "кому из юзеров отвечать"
# нужно, чтобы админ мог просто ответить (Reply) на сообщение и оно ушло нужному человеку
forward_map = {}


# ==== БАЗА ДАННЫХ (SQLite) ====
def init_db():
    conn = sqlite3.connect("users.db")
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE,
            first_name TEXT,
            last_name TEXT,
            instagram TEXT
        )
    """)
    conn.commit()
    conn.close()


def save_user(telegram_id: int, first_name: str, last_name: str, instagram: str):
    conn = sqlite3.connect("users.db")
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO users (telegram_id, first_name, last_name, instagram) VALUES (?, ?, ?, ?)",
        (telegram_id, first_name, last_name, instagram),
    )
    conn.commit()
    conn.close()


def get_user_name(telegram_id: int):
    conn = sqlite3.connect("users.db")
    cur = conn.cursor()
    cur.execute("SELECT first_name, last_name FROM users WHERE telegram_id = ?", (telegram_id,))
    row = cur.fetchone()
    conn.close()
    return row


def get_all_user_ids():
    conn = sqlite3.connect("users.db")
    cur = conn.cursor()
    cur.execute("SELECT telegram_id FROM users")
    rows = cur.fetchall()
    conn.close()
    return [row[0] for row in rows]


def get_all_users_details():
    conn = sqlite3.connect("users.db")
    cur = conn.cursor()
    cur.execute("SELECT first_name, last_name, instagram FROM users ORDER BY id")
    rows = cur.fetchall()
    conn.close()
    return rows


def get_users_count():
    conn = sqlite3.connect("users.db")
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    count = cur.fetchone()[0]
    conn.close()
    return count


# ==== СОСТОЯНИЯ (FSM) ====
class Registration(StatesGroup):
    waiting_for_full_name = State()
    waiting_for_instagram = State()


# ==== РЕГИСТРАЦИЯ ====
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.set_state(Registration.waiting_for_full_name)
    await message.answer("Йо! Как тебя зовут? Напиши Имя и Фамилию.")


@dp.message(Registration.waiting_for_full_name)
async def process_full_name(message: Message, state: FSMContext):
    text = message.text.strip()
    parts = text.split(maxsplit=1)

    if len(parts) < 2:
        await message.answer(
            "Напиши имя и фамилию вместе, через пробел — например: Иван Иванов"
        )
        return

    first_name, last_name = parts[0], parts[1]
    await state.update_data(first_name=first_name, last_name=last_name)
    await state.set_state(Registration.waiting_for_instagram)
    await message.answer(
        "Твой Instagram @username?\n"
        "Напиши «нет», если хочешь пропустить этот шаг."
    )


@dp.message(Registration.waiting_for_instagram)
async def process_instagram(message: Message, state: FSMContext):
    text = message.text.strip()
    instagram = "" if text.lower() == "нет" else text

    data = await state.get_data()
    first_name = data["first_name"]
    last_name = data["last_name"]

    save_user(message.from_user.id, first_name, last_name, instagram)

    await message.answer(
        "OFD PRIVATE SESSION\n"
        "06.09 / SAINT PETERSBURG\n\n"
        "Сбор гостей — 16:30\n"
        "Старт записи - 17:00\n\n"
        "📍 Севкабель Порт\n\n"
        "МУЗ порт\n"
        "Saint Petersburg, Gavan Historical Sector\n"
        "https://yandex.com/maps/org/muz_port/147139020301?si=2m83rrebngfn8r447bf0jcchbw\n\n"
        "Сохрани это сообщение и приходи вовремя.\n"
        "Dress code и остальные детали отправим позже.\n\n"
        "See you inside"
    )

    dress_code_caption = (
        "И ещё немного про дресс-код 🖤\n\n"
        "На площадке будет запись видео, нам важно сохранить цельную картинку в кадре. "
        "Мы собрали визуальное направление по цветам и настроению — это не строгие рамки, а ориентир.\n\n"
        "Выбирай образ, в котором тебе комфортно двигаться, танцевать и быть собой.\n\n"
        "Проявляй себя — увидимся 6 сентября"
    )
    photo = FSInputFile("dress_code.jpg")
    try:
        await message.answer_photo(photo, caption=dress_code_caption)
    except Exception as e:
        logging.warning(f"Не удалось отправить фото дресс-кода: {e}")
        await message.answer(dress_code_caption)
    await state.clear()


# ==== ПРОСМОТР ПОЛЬЗОВАТЕЛЕЙ (только для админа) ====
@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    count = get_users_count()
    await message.answer(f"Всего зарегистрировано: {count}")


@dp.message(Command("users"))
async def cmd_users(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    users = get_all_users_details()

    if not users:
        await message.answer("Пока никто не зарегистрировался.")
        return

    lines = []
    for i, (first_name, last_name, instagram) in enumerate(users, start=1):
        ig_part = f" — @{instagram}" if instagram else ""
        lines.append(f"{i}. {first_name} {last_name}{ig_part}")

    text = "\n".join(lines)

    # Telegram режет сообщения длиннее 4096 символов — разбиваем на части
    for chunk_start in range(0, len(text), 4000):
        await message.answer(text[chunk_start:chunk_start + 4000])


# ==== РАССЫЛКА (только для админа) ====
@dp.message(Command("broadcast"))
async def cmd_broadcast(message: Message):
    if message.from_user.id != ADMIN_ID:
        return  # игнорируем всех, кроме админа

    text = message.text.replace("/broadcast", "", 1).strip()

    if not text:
        await message.answer(
            "Напиши текст после команды, например:\n/broadcast Привет всем!"
        )
        return

    user_ids = get_all_user_ids()
    sent = 0
    failed = 0

    for user_id in user_ids:
        try:
            await bot.send_message(user_id, text)
            sent += 1
        except Exception as e:
            failed += 1
            logging.warning(f"Не удалось отправить {user_id}: {e}")
        await asyncio.sleep(0.05)  # небольшая пауза, чтобы не словить лимиты Telegram

    await message.answer(f"Рассылка завершена ✅\nОтправлено: {sent}\nНе доставлено: {failed}")


# ==== СВЯЗЬ С АДМИНОМ ====
@dp.message(Command("admin"), StateFilter(None))
async def cmd_call_admin(message: Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer("Это твоя же команда 🙂 просто отвечай на сообщения от юзеров через Reply.")
        return

    user_id = message.from_user.id
    support_active.add(user_id)

    user_row = get_user_name(user_id)
    display_name = f"{user_row[0]} {user_row[1]}" if user_row else message.from_user.full_name

    text_after_command = message.text.replace("/admin", "", 1).strip()

    header = f"🔔 {display_name} (id: {user_id}) хочет поговорить."
    sent = await bot.send_message(ADMIN_ID, header)
    forward_map[sent.message_id] = user_id

    if text_after_command:
        sent2 = await bot.send_message(ADMIN_ID, text_after_command)
        forward_map[sent2.message_id] = user_id

    await message.answer("Сообщение отправлено администратору, дождись ответа здесь же 🖤")


# ==== ОБРАБОТКА ОТВЕТА АДМИНА (Reply на пересланное сообщение) ====
@dp.message(F.from_user.id == ADMIN_ID, F.reply_to_message)
async def admin_reply(message: Message):
    replied_id = message.reply_to_message.message_id

    if replied_id not in forward_map:
        return  # это Reply не на сообщение юзера, игнорируем

    target_user_id = forward_map[replied_id]

    try:
        await bot.send_message(target_user_id, message.text)
        await message.answer("Отправлено ✅")
    except Exception as e:
        await message.answer(f"Не получилось отправить: {e}")


# ==== ЛЮБОЕ СВОБОДНОЕ СООБЩЕНИЕ ОТ ЮЗЕРА (после регистрации) ====
@dp.message(StateFilter(None))
async def catch_all(message: Message):
    user_id = message.from_user.id

    if user_id == ADMIN_ID:
        return  # админ не получает подсказки

    if user_id in support_active:
        # пересылаем админу автоматически
        user_row = get_user_name(user_id)
        display_name = f"{user_row[0]} {user_row[1]}" if user_row else message.from_user.full_name

        sent = await bot.send_message(ADMIN_ID, f"✉️ {display_name} (id: {user_id}):\n{message.text}")
        forward_map[sent.message_id] = user_id
        return

    await message.answer("Хочешь написать администратору? Напиши команду /admin")


# ==== ЗАПУСК ====
async def main():
    init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
