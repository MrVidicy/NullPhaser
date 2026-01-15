# bot_aiogram.py
import asyncio
import logging
import html
import os
import random
import io
import time

import aiohttp
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt



from aiogram import Bot, Dispatcher
from aiogram.types import Message, BufferedInputFile
from aiogram.filters import Command
from aiogram import types

import json
import os

DATA_FILE = "data.json"

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"USER_NICKS": {}, "STALK_LIST_CF": {}, "STALK_LIST_AC": {}}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# Загрузка данных при старте
data = load_data()
USER_NICKS = data["USER_NICKS"]
STALK_LIST_CF = data["STALK_LIST_CF"]
STALK_LIST_AC = data["STALK_LIST_AC"]





# ---------- Конфигурация ----------
logging.basicConfig(level=logging.INFO)
REQUEST_TIMEOUT = 10
BOT_TOKEN = os.environ.get("BOT_TOKEN", "7968511826:AAEs2YFFTeK2p5DMylIkiR602aURFFys-vw")
bot = Bot(BOT_TOKEN)
dp = Dispatcher()

# ---------- Глобальная сессия ----------
GLOBAL_SESSION = None
async def start_global_session():
    global GLOBAL_SESSION
    if GLOBAL_SESSION is None:
        GLOBAL_SESSION = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT))
        logging.info("Global aiohttp session started")

async def close_global_session():
    global GLOBAL_SESSION
    if GLOBAL_SESSION:
        await GLOBAL_SESSION.close()
        GLOBAL_SESSION = None
        logging.info("Global aiohttp session closed")

# ---------- Списки слежки ----------
STALK_LIST_CF = {}
STALK_LIST_AC = {}

stalking_active_cf = True
stalking_active_ac = True

last_solved_cf = {}
last_solved_ac = {}

# ---------- Хранилище ников ----------
USER_NICKS = {}  # user_id -> {"cf": nick, "ac": nick}

# ---------- Утилиты ----------
def esc(s):
    return html.escape(str(s), quote=True)

async def safe_get_json(url, params=None, retries=3, delay=1):
    await start_global_session()
    global GLOBAL_SESSION
    backoff = delay
    for attempt in range(1, retries + 1):
        try:
            async with GLOBAL_SESSION.get(url, params=params) as r:
                r.raise_for_status()
                return await r.json()
        except Exception as e:
            if attempt < retries:
                logging.warning(f"HTTP/JSON error for {url} (attempt {attempt}/{retries}): {e} — retrying in {backoff}s")
                await asyncio.sleep(backoff)
                backoff *= 2
            else:
                logging.exception(f"HTTP/JSON final failure for {url}: {e}")
                return None

def get_stored_nick(user_id, platform):
    data = USER_NICKS.get(user_id)
    if not data:
        return None
    return data.get(platform)

async def get_handle_or_ask(message: Message, platform: str):
    """
    platform: 'cf' или 'ac'
    Берёт ник из команды, или из /me, если нет — пишет пользователю.
    """
    parts = message.text.split()
    if len(parts) >= 2 and parts[1].strip():
        return parts[1].strip()

    uid = message.from_user.id
    stored = get_stored_nick(uid, platform)
    if stored:
        return stored

    await message.reply(
        f"🐶 Ник не указан и не найден в /me. Установи свой ник командой:\n"
        f"<code>/set_me cf {esc('ник')}</code> или <code>/set_me ac {esc('ник')}</code> "
        f"(или <code>/set_me {esc('ник')}</code> для обоих).",
        parse_mode='HTML'
    )
    return None


# ---------- Фоновый сталкер ----------
async def stalker_logic():
    global stalking_active_cf, stalking_active_ac
    logging.info("Stalker task started")
    while True:
        # CF
        if stalking_active_cf:
            cf_chat_map = {chat: list(handles) for chat, handles in STALK_LIST_CF.items()}
            handle_to_chats = {}
            for chat, handles in cf_chat_map.items():
                for h in handles:
                    handle_to_chats.setdefault(h, []).append(chat)
            for handle, chats in handle_to_chats.items():
                try:
                    logging.info(f"[CF] checking handle {handle} for {len(chats)} chats")
                    res = await safe_get_json("https://codeforces.com/api/user.status", params={"handle": handle, "from": 1, "count": 1})
                    if res and res.get("status") == "OK" and res.get("result"):
                        sub = res["result"][0]
                        if sub.get("verdict") == "OK":
                            sub_id = sub.get("id")
                            if last_solved_cf.get(handle) != sub_id:
                                p = sub['problem']
                                p_id = f"{p.get('contestId')}{p.get('index')}"
                                difficulty = p.get('rating', '???')
                                link = f"https://codeforces.com/contest/{p['contestId']}/problem/{p['index']}"
                                msg = (
                                    "🐶 Вуф! Твоя верная собачка сообщает:\n\n"
                                    f"🔥 <b>CF</b> — <b>{esc(handle)}</b> решил задачу!\n"
                                    f"🎯 {esc(p_id)}: {esc(p.get('name'))} (Сложность: <b>{esc(difficulty)}</b>)\n"
                                    f"🔗 <a href=\"{esc(link)}\">Перейти к задаче</a>"
                                )
                                for chat_id in chats:
                                    try:
                                        await bot.send_message(chat_id, msg, parse_mode='HTML', disable_web_page_preview=True)
                                    except Exception:
                                        logging.exception(f"[CF] Failed to notify chat {chat_id} for {handle}")
                                last_solved_cf[handle] = sub_id
                    else:
                        logging.debug(f"[CF] No new result for {handle}")
                except Exception:
                    logging.exception(f"[CF] stalker error for {handle}")
                await asyncio.sleep(0.5)

        # AC
        if stalking_active_ac:
            ac_chat_map = {chat: list(handles) for chat, handles in STALK_LIST_AC.items()}
            handle_to_chats_ac = {}
            for chat, handles in ac_chat_map.items():
                for h in handles:
                    handle_to_chats_ac.setdefault(h, []).append(chat)
            for handle, chats in handle_to_chats_ac.items():
                try:
                    logging.info(f"[AC] checking handle {handle} for {len(chats)} chats")
                    kenko_subs = await safe_get_json("https://kenkoooo.com/atcoder/atcoder-api/v3/user/submissions", params={"user": handle})
                    if kenko_subs and len(kenko_subs) > 0:
                        sub = kenko_subs[-1]
                        if sub.get('result') == 'AC':
                            sub_id = sub.get('id') or f"{sub.get('contest_id')}#{sub.get('problem_id')}#{sub.get('epoch_second')}"
                            if last_solved_ac.get(handle) != sub_id:
                                title = sub.get('problem_id') or sub.get('title') or "Unknown"
                                contest = sub.get('contest_id')
                                link = (f"https://atcoder.jp/contests/{contest}/tasks/{sub.get('problem_id')}"
                                        if contest else f"https://atcoder.jp/users/{handle}/submissions")
                                msg = (
                                    "🐶 Вуф! Твоя верная собачка сообщает:\n\n"
                                    f"🔥 <b>AC</b> — <b>{esc(handle)}</b> AC!\n"
                                    f"🎯 {esc(title)}\n"
                                    f"🔗 <a href=\"{esc(link)}\">Перейти</a>"
                                )
                                for chat_id in chats:
                                    try:
                                        await bot.send_message(chat_id, msg, parse_mode='HTML', disable_web_page_preview=True)
                                    except Exception:
                                        logging.exception(f"[AC] Failed to notify chat {chat_id} for {handle}")
                                last_solved_ac[handle] = sub_id
                    else:
                        logging.debug(f"[AC] No submissions for {handle} or API returned nothing")
                except Exception:
                    logging.exception(f"[AC] stalker error for {handle}")
                await asyncio.sleep(0.5)

        await asyncio.sleep(60)

# ---------- Команды ----------

@dp.message(Command("start"))
async def send_welcome(message: Message):
    await message.reply("🐶 Привет! Я твоя верная собачка и слежу за твоим прогрессом!\nПиши /help.")

@dp.message(Command("help"))
async def help_command(message: Message):
    help_text = (
        "🐶 Команды бота:\n\n"
        "👤 Личные:\n"
        "  /set_me [cf|ac] ник — установить ник для CF/AC или обоих\n"
        "  /me — показать текущие ники\n\n"
        "🏆 Codeforces:\n"
        "  /cf_status [ник] — статус пользователя\n"
        "  /cf_train [ник] — тренировочный план\n"
        "  /cf_follow [ник] — следить за пользователем\n"
        "  /cf_unfollow [ник] — перестать следить\n"
        "  /cf_list — показать список пользователей, за которыми следят\n\n"
        "🎯 AtCoder:\n"
        "  /ac_status [ник] — статус пользователя\n"
        "  /ac_follow [ник] — следить за пользователем\n"
        "  /ac_unfollow [ник] — перестать следить\n"
        "  /ac_list — показать список пользователей, за которыми следят\n"
        "😈 База:\n"
        "🐶 Если ник не указан, бот возьмёт его из /me.\n"
        "  /start — приветствие\n"
        "  /help — это сообщение\n"
        "  /help_more — описание команд подробнее\n"
    )
    await message.reply(help_text, parse_mode='HTML')

@dp.message(Command("help_more"))
async def help_more_command(message: Message):
    help_text = (
        "🐶 Подробные команды бота:\n\n"
        "👤 Личные команды:\n"
        "  /set_me [cf|ac] ник — устанавливает твой ник для Codeforces (cf) или AtCoder (ac). Если платформа не указана, устанавливается сразу для обеих.\n"
        "  /me — показывает текущие установленные ники для CF и AC.\n\n"
        "🏆 Codeforces:\n"
        "  /cf_status [ник] — выводит рейтинг, ранг, общее количество решённых задач и распределение по сложности.\n"
        "  /cf_graph [ник] — строит график изменения рейтинга.\n"
        "  /cf_gimme [рейтинг] [тег] — случайная задача, можно указать желаемый рейтинг и тег.\n"
        "  /cf_train [ник] — генерирует тренировочный план по слабым тегам и уровню пользователя.\n"
        "  /cf_follow [ник] — добавляет пользователя в слежку.\n"
        "  /cf_unfollow [ник] — убирает пользователя из слежки.\n"
        "  /cf_list — показывает список пользователей в слежке.\n\n"
        "🎯 AtCoder:\n"
        "  /ac_status [ник] — показывает рейтинг, макс. рейтинг, количество решённых задач.\n"
        "  /ac_graph [ник] — пока не реализован.\n"
        "  /ac_gimme [рейтинг] — случайная задача.\n"
        "  /ac_train [ник] — формирует тренировочный план по сложностям и не решённым задачам.\n"
        "  /ac_follow [ник] — добавить пользователя в слежку.\n"
        "  /ac_unfollow [ник] — убрать пользователя из слежки.\n"
        "  /ac_list — показать список пользователей в слежке.\n"
    )
    await message.reply(help_text, parse_mode='HTML')

# --- set_me / me ---
@dp.message(Command("set_me"))
async def set_me_cmd(message: Message):
    parts = message.text.split()
    if len(parts) < 2:
        await message.reply("🐶 Использование: /set_me [cf|ac] ник или /set_me ник для обоих.")
        return
    uid = message.from_user.id
    if len(parts) >= 3 and parts[1].lower() in ("cf", "ac"):
        platform = parts[1].lower()
        nick = parts[2]
        USER_NICKS.setdefault(uid, {"cf": None, "ac": None})[platform] = nick
        await message.reply(f"✅ Установил твой {platform.upper()} ник: <b>{esc(nick)}</b>", parse_mode='HTML')
    else:
        nick = parts[1]
        USER_NICKS.setdefault(uid, {"cf": None, "ac": None})["cf"] = nick
        USER_NICKS.setdefault(uid, {"cf": None, "ac": None})["ac"] = nick
        await message.reply(f"✅ Установил твой ник для CF и AC: <b>{esc(nick)}</b>", parse_mode='HTML')

    # --- Сохраняем данные в файл ---
    save_data({
        "USER_NICKS": USER_NICKS,
        "STALK_LIST_CF": STALK_LIST_CF,
        "STALK_LIST_AC": STALK_LIST_AC
    })

@dp.message(Command("me"))
async def me_cmd(message: Message):
    uid = message.from_user.id
    data = USER_NICKS.get(uid)
    if not data:
        await message.reply("🐶 Ник не установлен. /set_me ник")
        return
    cf_n = data.get("cf") or "—"
    ac_n = data.get("ac") or "—"
    await message.reply(f"👤 Твои ники:\nCF: <b>{esc(cf_n)}</b>\nAC: <b>{esc(ac_n)}</b>", parse_mode='HTML')

# ---------- CF команды ----------
@dp.message(Command("cf_status"))
async def cf_status(message: Message):
    handle = await get_handle_or_ask(message, "cf")
    if not handle: return
    await message.reply(f"🐶 Смотрю статистику {esc(handle)}...", parse_mode='HTML')
    url_info = f"https://codeforces.com/api/user.info?handles={handle}"
    info = await safe_get_json(url_info)
    if not info or info.get("status") != "OK": return await message.reply("❌ Не могу получить данные CF.")
    user = info["result"][0]
    rank = user.get("rank", "—")
    rating = user.get("rating", "—")
    max_rating = user.get("maxRating", "—")
    avatar = user.get("titlePhoto")
    url_subs = f"https://codeforces.com/api/user.status?handle={handle}&from=1&count=1000"
    res = await safe_get_json(url_subs)
    solved_count = 0
    difficulty_stats = {}
    if res and res.get("status") == "OK":
        for sub in res["result"]:
            if sub.get("verdict") == "OK":
                solved_count += 1
                rating_p = sub["problem"].get("rating")
                if rating_p: difficulty_stats[rating_p] = difficulty_stats.get(rating_p,0)+1
    diff_lines = "\n".join([f"🔹 {r}: {c} шт." for r,c in sorted(difficulty_stats.items())]) or "—"
    profile_link = f"https://codeforces.com/profile/{handle}"
    text = f"👤 CF: {esc(handle)}\n🏆 Ранг: {esc(rank)}\n📈 Рейтинг: {esc(rating)} (max: {esc(max_rating)})\n✅ Всего решено: {solved_count}\n📊 Сложность задач:\n{diff_lines}\n🔗 Профиль: {profile_link}"
    if avatar:
        try: await message.answer_photo(avatar, caption=text, parse_mode='HTML')
        except: await message.reply(text, parse_mode='HTML')
    else: await message.reply(text, parse_mode='HTML')


@dp.message(Command("cf_graph"))
async def cf_graph_cmd(message):
    handle = await get_handle_or_ask(message, "cf")
    if not handle: return

    url_user = f"https://codeforces.com/api/user.rating?handle={handle}"
    res = await safe_get_json(url_user)
    if not res or res.get("status") != "OK":
        await message.reply("❌ Не могу получить данные для графика CF.")
        return

    ratings = res["result"]
    if not ratings:
        await message.reply("❌ Нет данных для графика CF.")
        return

    x = list(range(1, len(ratings)+1))
    y = [r["newRating"] for r in ratings]
    contests = [r["contestName"] for r in ratings]

    plt.figure(figsize=(10,5))
    plt.plot(x, y, marker='o', color='blue')
    plt.title(f"CF Rating Graph — {handle}")
    plt.xlabel("Contests")
    plt.ylabel("Rating")
    plt.grid(True)
    plt.xticks(x, [c[:10]+"…" if len(c)>10 else c for c in contests], rotation=45, ha='right')

    buf = io.BytesIO()
    plt.tight_layout()
    plt.savefig(buf, format='PNG')
    buf.seek(0)
    plt.close()

    buf.seek(0)
    await message.answer_photo(
        BufferedInputFile(buf.getvalue(), filename="cf_graph.png"),
        caption=f"📈 График рейтинга CF — {esc(handle)}"
    )






@dp.message(Command("cf_gimme"))
async def cf_gimme_cmd(message: types.Message):
    parts = message.text.split()
    uid = message.from_user.id
    handle = parts[1] if len(parts) > 1 else get_stored_nick(uid, "cf")
    rating = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
    tag = parts[3] if len(parts) > 3 else None

    if not handle:
        await message.reply("🐶 Ник не указан и не найден в /me. Установи командой /set_me cf <ник>")
        return

    data = await safe_get_json("https://codeforces.com/api/problemset.problems")
    if not data or data.get("status") != "OK":
        return await message.reply("❌ Не могу получить задачи CF.")

    problems = data["result"]["problems"]

    # Получаем решённые
    subs_data = await safe_get_json(f"https://codeforces.com/api/user.status?handle={handle}&from=1&count=1000")
    solved_set = set()
    if subs_data and subs_data.get("status") == "OK":
        for sub in subs_data["result"]:
            if sub.get("verdict") == "OK":
                p = sub["problem"]
                solved_set.add(f"{p['contestId']}#{p['index']}")

    # Фильтруем задачи строго по рейтингу
    candidates = []
    for p in problems:
        key = f"{p['contestId']}#{p['index']}"
        if key in solved_set:
            continue

        # строго фильтруем по рейтингу
        if rating is not None:
            if p.get("rating") is None or p["rating"] != rating:
                continue

        # фильтруем по тегу
        if tag and tag not in p.get("tags", []):
            continue

        candidates.append(p)
        
    if not candidates:
        return await message.reply(f"🐶 Не нашлось задач с рейтингом {rating} 😢")

    chosen = random.choice(candidates)
    link = f"https://codeforces.com/contest/{chosen['contestId']}/problem/{chosen['index']}"
    await message.reply(f"🎯 {chosen['name']} ({chosen.get('rating', '??')})\n🔗 {link}", parse_mode="HTML")





# --- CF train ---
@dp.message(Command("cf_train"))
async def cf_train_cmd(message: Message):
    handle = await get_handle_or_ask(message, "cf")
    if not handle: return
    await message.reply(f"🐶 Анализирую {esc(handle)}...", parse_mode='HTML')
    url_user = f"https://codeforces.com/api/user.info?handles={handle}"
    info = await safe_get_json(url_user)
    rating = info["result"][0].get("rating",0) if info and info.get("status")=="OK" else 0
    url_subs = f"https://codeforces.com/api/user.status?handle={handle}&from=1&count=1000"
    res = await safe_get_json(url_subs)
    solved = set()
    tag_counts = {}
    if res and res.get("status")=="OK":
        for sub in res["result"]:
            if sub.get("verdict")=="OK":
                p = sub["problem"]
                key = f"{p.get('contestId')}#{p.get('index')}"
                solved.add(key)
                for t in p.get("tags",[]): tag_counts[t] = tag_counts.get(t,0)+1
    weak_tags = sorted(tag_counts,key=lambda x:tag_counts[x])[:3] if tag_counts else ["implementation","math","greedy"]
    url_ps = "https://codeforces.com/api/problemset.problems"
    ps = await safe_get_json(url_ps)
    all_probs = []
    if ps and ps.get("status")=="OK":
        for p in ps["result"]["problems"]:
            key = f"{p.get('contestId')}#{p.get('index')}"
            if key not in solved: all_probs.append(p)
    levels = [("🟢 База", rating),("🟡 Прогресс", rating+100),("🔴 Вызов", rating+200)]
    selected_by_level = []
    for level_name,lvl_rating in levels:
        level_tasks=[]
        for tag in weak_tags+["any"]:
            candidates=[p for p in all_probs if (p.get('rating') and abs(p.get('rating')-lvl_rating)<=100) and (tag=="any" or tag in p.get("tags",[]))]
            if not candidates and tag!="any": candidates=[p for p in all_probs if p.get('rating') and abs(p.get('rating')-lvl_rating)<=100]
            if candidates:
                chosen=random.choice(candidates)
                all_probs.remove(chosen)
                level_tasks.append((tag if tag in chosen.get("tags",[]) else "any",chosen))
        selected_by_level.append((level_name,level_tasks))
    text_lines=[f"🏋️ Тренировочный марафон для {esc(handle)}",f"🎯 Твои цели: {', '.join(weak_tags)}\n"]
    for level_name,tasks in selected_by_level:
        text_lines.append(f"{level_name} ({tasks[0][1].get('rating','?')}):")
        for tag,p in tasks:
            t=tag or "any"
            link=f"https://codeforces.com/contest/{p['contestId']}/problem/{p['index']}"
            text_lines.append(f"└ {t}: <a href='{esc(link)}'>{esc(p.get('name'))}</a>")
    await message.reply("\n".join(text_lines), parse_mode='HTML', disable_web_page_preview=True)

# --- CF follow/unfollow/list ---
@dp.message(Command("cf_follow"))
async def cf_follow_cmd(message: Message):
    handle = await get_handle_or_ask(message,"cf")
    if not handle: return
    chat_id=message.chat.id
    STALK_LIST_CF.setdefault(chat_id,[])
    if handle not in STALK_LIST_CF[chat_id]:
        STALK_LIST_CF[chat_id].append(handle)
        await message.reply(f"✅ Слежу за <b>{esc(handle)}</b> на CF!",parse_mode='HTML')
    else: await message.reply("🐶 Уже в списке.")

    STALK_LIST_CF.setdefault(chat_id, [])
    if handle not in STALK_LIST_CF[chat_id]:
        STALK_LIST_CF[chat_id].append(handle)
        save_data({"USER_NICKS": USER_NICKS, "STALK_LIST_CF": STALK_LIST_CF, "STALK_LIST_AC": STALK_LIST_AC})

@dp.message(Command("cf_unfollow"))
async def cf_unfollow_cmd(message: Message):
    handle = await get_handle_or_ask(message,"cf")
    if not handle: return
    chat_id=message.chat.id
    if chat_id in STALK_LIST_CF and handle in STALK_LIST_CF[chat_id]:
        STALK_LIST_CF[chat_id].remove(handle)
        await message.reply(f"✅ Убрал <b>{esc(handle)}</b> из CF-списка.",parse_mode='HTML')
    else: await message.reply("🐶 Его и так нет в списке.")

    STALK_LIST_CF.setdefault(chat_id, [])
    if handle not in STALK_LIST_CF[chat_id]:
        STALK_LIST_CF[chat_id].append(handle)
        save_data({"USER_NICKS": USER_NICKS, "STALK_LIST_CF": STALK_LIST_CF, "STALK_LIST_AC": STALK_LIST_AC})

@dp.message(Command("cf_list"))
async def cf_list_cmd(message: Message):
    handles=STALK_LIST_CF.get(message.chat.id,[])
    if not handles: return await message.reply("🐶 CF список пуст.")
    await message.reply("🕵️ <b>CF список:</b>\n"+"\n".join(f"• {esc(h)}" for h in handles),parse_mode='HTML')

# --- AC команды ---
@dp.message(Command("ac_status"))
async def ac_status(message: Message):
    handle = await get_handle_or_ask(message,"ac")
    if not handle: return
    await message.reply(f"🐶 Смотрю статистику {esc(handle)}...",parse_mode='HTML')
    url_info=f"https://kenkoooo.com/atcoder/atcoder-api/v3/user/info?user={handle}"
    info=await safe_get_json(url_info)
    if not info: return await message.reply("❌ Не могу получить данные AC.")
    rating=info.get("rating","—")
    highest=info.get("highestRating","—")
    avatar=info.get("avatar")
    url_subs=f"https://kenkoooo.com/atcoder/atcoder-api/v3/user/submissions?user={handle}"
    subs=await safe_get_json(url_subs)
    solved_count=0
    difficulty_stats={}
    if subs:
        for sub in subs:
            if sub.get("result")=="AC": solved_count+=1
    text=f"👤 AC: {esc(handle)}\n📈 Рейтинг: {rating} (max: {highest})\n✅ Решено задач: {solved_count}"
    if avatar:
        try: await message.answer_photo(avatar,caption=text,parse_mode='HTML')
        except: await message.reply(text,parse_mode='HTML')
    else: await message.reply(text,parse_mode='HTML')

@dp.message(Command("ac_gimme"))
async def ac_gimme_cmd(message: types.Message):
    parts = message.text.split()
    uid = message.from_user.id
    handle = parts[1] if len(parts) > 1 else get_stored_nick(uid, "ac")
    rating = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None

    if not handle:
        await message.reply("🐶 Ник не указан и не найден в /me. Установи командой /set_me ac <ник>")
        return

    # Получаем список задач AC
    data = await safe_get_json("https://atcoder.jp/contests/all/tasks.json")  # пример ссылки
    if not data:
        return await message.reply("❌ Не могу получить задачи AC.")

    problems = data  # Тут структура зависит от AC API
    solved_set = set()  # Если есть API для решённых, можно заполнить

    # Фильтруем задачи
    candidates = []
    for p in problems:
        key = p["id"]
        if key in solved_set:
            continue
        if rating and "difficulty" in p and abs(p["difficulty"] - rating) > 50:
            continue
        candidates.append(p)

    if not candidates:
        return await message.reply("🐶 Не нашлось подходящих задач 😢")

    chosen = random.choice(candidates)
    link = f"https://atcoder.jp/contests/{chosen['contest_id']}/tasks/{chosen['id']}"
    await message.reply(f"🎯 {chosen['name']}({chosen.get('difficulty', '??')})\n🔗 {link}", parse_mode="HTML")


@dp.message(Command("ac_follow"))
async def ac_follow_cmd(message: Message):
    handle = await get_handle_or_ask(message, "ac")
    if not handle: return
    chat_id = message.chat.id
    STALK_LIST_AC.setdefault(chat_id, [])
    if handle not in STALK_LIST_AC[chat_id]:
        STALK_LIST_AC[chat_id].append(handle)
        await message.reply(f"✅ Слежу за <b>{esc(handle)}</b> на AC!", parse_mode='HTML')
        save_data({
            "USER_NICKS": USER_NICKS,
            "STALK_LIST_CF": STALK_LIST_CF,
            "STALK_LIST_AC": STALK_LIST_AC
        })
    else:
        await message.reply("🐶 Уже в списке.")

@dp.message(Command("ac_unfollow"))
async def ac_unfollow_cmd(message: Message):
    handle = await get_handle_or_ask(message, "ac")
    if not handle: return
    chat_id = message.chat.id
    if chat_id in STALK_LIST_AC and handle in STALK_LIST_AC[chat_id]:
        STALK_LIST_AC[chat_id].remove(handle)
        await message.reply(f"✅ Убрал <b>{esc(handle)}</b> из AC-списка.", parse_mode='HTML')
        save_data({
            "USER_NICKS": USER_NICKS,
            "STALK_LIST_CF": STALK_LIST_CF,
            "STALK_LIST_AC": STALK_LIST_AC
        })
    else:
        await message.reply("🐶 Его и так нет в списке.")


@dp.message(Command("ac_list"))
async def ac_list_cmd(message: Message):
    handles=STALK_LIST_AC.get(message.chat.id,[])
    if not handles: return await message.reply("🐶 AC список пуст.")
    await message.reply("🕵️ <b>AC список:</b>\n"+"\n".join(f"• {esc(h)}" for h in handles),parse_mode='HTML')


@dp.message(Command("ac_graph"))
async def ac_graph_cmd(message):
    handle = await get_handle_or_ask(message, "ac")
    if not handle: return

    url_subs = f"https://kenkoooo.com/atcoder/atcoder-api/v3/user/rating?user={handle}"
    res = await safe_get_json(url_subs)
    if not res:
        await message.reply("❌ Не могу получить данные для графика AC.")
        return

    x = [datetime.fromtimestamp(r["epoch_second"]) for r in res]
    y = [r["new_rating"] for r in res]

    plt.figure(figsize=(10,5))
    plt.plot(x, y, marker='o', color='green')
    plt.title(f"AC Rating Graph — {handle}")
    plt.xlabel("Дата")
    plt.ylabel("Rating")
    plt.grid(True)
    plt.xticks(rotation=45)

    buf = io.BytesIO()
    plt.tight_layout()
    plt.savefig(buf, format='PNG')
    buf.seek(0)
    plt.close()

    buf.seek(0)
    await message.answer_photo(
        BufferedInputFile(buf.getvalue(), filename="cf_graph.png"),
        caption=f"📈 График рейтинга CF — {esc(handle)}"
    )

# --- AC train ---
@dp.message(Command("ac_train"))
async def ac_train_cmd(message: Message):
    handle = await get_handle_or_ask(message, "ac")
    if not handle:
        return

    await message.reply(f"🐶 Анализирую {esc(handle)}...", parse_mode='HTML')

    # Берём все задачи
    url_problems = "https://kenkoooo.com/atcoder/atcoder-api/v3/problems"
    problems = await safe_get_json(url_problems)
    if not problems:
        await message.reply("❌ Не могу получить список задач AC.")
        return

    # Берём все успешные сабмиссии пользователя
    url_subs = f"https://kenkoooo.com/atcoder/atcoder-api/v3/user/submissions?user={handle}"
    subs = await safe_get_json(url_subs)
    solved = set()
    if subs:
        for sub in subs:
            if sub.get("result") == "AC":
                solved.add(sub.get("problem_id"))

    # Разделяем задачи по уровню сложности
    # Берём средний рейтинг пользователя
    url_info = f"https://kenkoooo.com/atcoder/atcoder-api/v3/user/info?user={handle}"
    info = await safe_get_json(url_info)
    rating = info.get("rating", 0) if info else 0

    levels = [("🟢 База", rating), ("🟡 Прогресс", rating + 100), ("🔴 Вызов", rating + 200)]
    selected_by_level = []

    for level_name, lvl_rating in levels:
        level_tasks = []
        # Выбираем 3 случайные задачи для уровня
        candidates = [p for p in problems if p.get("difficulty") and abs(int(p["difficulty"]) - lvl_rating) <= 100 and p["id"] not in solved]
        if not candidates:
            candidates = [p for p in problems if p.get("difficulty") and p["id"] not in solved]
        for _ in range(3):
            if candidates:
                chosen = random.choice(candidates)
                candidates.remove(chosen)
                level_tasks.append(chosen)
        selected_by_level.append((level_name, level_tasks))

    # Формируем текст для ответа
    text_lines = [f"🏋️ Тренировочный марафон для {esc(handle)}\n🎯 Цель: развивать навыки и решать задачи\n"]
    for level_name, tasks in selected_by_level:
        if not tasks:
            continue
        text_lines.append(f"{level_name}:")
        for p in tasks:
            contest = p.get("contest_id")
            pid = p.get("id")
            title = p.get("title")
            link = f"https://atcoder.jp/contests/{contest}/tasks/{pid}" if contest else f"https://atcoder.jp/tasks/{pid}"
            text_lines.append(f"└ {esc(pid)}: <a href='{esc(link)}'>{esc(title)}</a>")

    await message.reply("\n".join(text_lines), parse_mode='HTML', disable_web_page_preview=True)



@dp.message(Command("cf_stalk_on"))
async def cf_stalk_on_cmd(message: Message):
    global stalking_active_cf
    stalking_active_cf = True
    await message.reply("✅ Уведомления CF включены.", parse_mode='HTML')

@dp.message(Command("cf_stalk_off"))
async def cf_stalk_off_cmd(message: Message):
    global stalking_active_cf
    stalking_active_cf = False
    await message.reply("⚠️ Уведомления CF отключены.", parse_mode='HTML')

@dp.message(Command("ac_stalk_on"))
async def ac_stalk_on_cmd(message: Message):
    global stalking_active_ac
    stalking_active_ac = True
    await message.reply("✅ Уведомления AC включены.", parse_mode='HTML')

@dp.message(Command("ac_stalk_off"))
async def ac_stalk_off_cmd(message: Message):
    global stalking_active_ac
    stalking_active_ac = False
    await message.reply("⚠️ Уведомления AC отключены.", parse_mode='HTML')


# ---------- Main ----------
async def main():
    await start_global_session()
    asyncio.create_task(stalker_logic())
    await dp.start_polling(bot)

if __name__ == "__main__":
    try: asyncio.run(main())
    finally: asyncio.run(close_global_session())
